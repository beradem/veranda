"""Real Estate Signal Engine — NYC PLUTO property data for HNW leads.

NYC publishes PLUTO (Primary Land Use Tax Lot Output) — a dataset containing
owner names, assessed values, and addresses for every property in the city.
Think of it as a public phone book for property owners, but with dollar amounts.

This engine queries PLUTO via the Socrata Open Data API (SODA), estimates true
market values using NYC tax class multipliers, and returns standardized Lead
objects for high-value property owners.

Free, no login required, ~870K+ tax lots available.
"""

import logging
import re
from typing import Optional

from sodapy import Socrata

from src.models.lead import Lead, LeadSource

logger = logging.getLogger(__name__)

# --- NYC PLUTO SODA API config ---
SOCRATA_DOMAIN = "data.cityofnewyork.us"
PLUTO_RESOURCE_ID = "64uk-42ks"

# NYC assessed values are a fraction of true market value. These multipliers
# reverse that fraction so we can estimate what the property is actually worth.
# Class 1 = 1-3 family homes (assessed at ~6% of market value)
# Class 2 = apartments/condos 4+ units (assessed at ~45%)
# Class 3 = utility properties (varies, ~50%)
# Class 4 = commercial (assessed at ~45%)
TAX_CLASS_MULTIPLIERS: dict[str, float] = {
    "1": 16.67,
    "2": 2.22,
    "3": 2.00,
    "4": 2.22,
}

# Neighborhood presets — each neighborhood maps to its NYC zip codes
# 50 highest-median-price NYC neighborhoods, ordered by median home price.
# Each maps to the zip codes that cover that neighborhood.
NEIGHBORHOOD_ZIP_CODES: dict[str, list[str]] = {
    # --- Manhattan ---
    "Hudson Yards": ["10001", "10018"],
    "SoHo": ["10012", "10013"],
    "Tribeca": ["10007", "10013"],
    "NoHo": ["10003", "10012"],
    "Central Park South": ["10019"],
    "NoLIta": ["10012"],
    "Hudson Square": ["10013", "10014"],
    "Carnegie Hill": ["10128"],
    "NoMad": ["10010", "10016"],
    "Central Midtown": ["10017", "10022", "10036"],
    "West Village": ["10014"],
    "Two Bridges": ["10002", "10038"],
    "Flatiron District": ["10010"],
    "Garment District": ["10018", "10036"],
    "Lenox Hill": ["10021", "10065", "10075"],
    "Lincoln Square": ["10023"],
    "Greenwich Village": ["10003", "10011", "10012"],
    "Theatre District": ["10019", "10036"],
    "Chelsea": ["10001", "10011"],
    "Upper West Side": ["10023", "10024", "10025"],
    "Financial District": ["10004", "10005", "10006", "10038"],
    "East Village": ["10003", "10009"],
    "Gramercy Park": ["10003", "10010"],
    "Manhattan Valley": ["10025"],
    "Stuyvesant Town": ["10009", "10010"],
    "Lower East Side": ["10002"],
    # --- Brooklyn ---
    "Cobble Hill": ["11201", "11231"],
    "DUMBO": ["11201"],
    "Boerum Hill": ["11201", "11217"],
    "Columbia St Waterfront": ["11231"],
    "Carroll Gardens": ["11231"],
    "Williamsburg": ["11211", "11249"],
    "Greenwood Heights": ["11232"],
    "Park Slope": ["11215", "11217"],
    "Greenpoint": ["11222"],
    "Gowanus": ["11215", "11217"],
    "Fort Greene": ["11205", "11217"],
    "Red Hook": ["11231"],
    "Manhattan Beach": ["11235"],
    "Mill Basin": ["11234"],
    "Prospect Heights": ["11238"],
    "Brooklyn Heights": ["11201"],
    "Downtown Brooklyn": ["11201", "11217"],
    "Prospect-Lefferts Gdns": ["11225"],
    "Clinton Hill": ["11205", "11238"],
    # --- Queens ---
    "Malba": ["11357"],
    "Fresh Meadows": ["11365", "11366"],
    "Belle Harbor": ["11694"],
    "Hunters Point": ["11101"],
    "Long Island City": ["11101", "11109"],
}

# Patterns that indicate the "owner" is actually a company, institution,
# government entity, or placeholder — not a real person we can contact.
_ENTITY_PATTERNS = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|TRUST|LTD|LP|L\.P|ASSOCIATES|HOLDINGS|"
    r"PROPERTIES|PARTNERS|GROUP|REALTY|MGMT|MANAGEMENT|CO\b|COMPANY|"
    r"ESTATE OF|C/O|INVESTMENTS|"
    # Government, diplomatic, and institutions
    r"CITY OF|STATE OF|DEPARTMENT|AUTHORITY|GOVERNMENT|UNITED STATES|"
    r"REPUBLIC|RPBLC|REP\b|PERMANENT MISSION|CONSULATE|EMBASSY|HOLY SEE|"
    r"BUNDERSREPUBLIK|MISSION ETC|"
    # Non-profits and organizations
    r"MUSEUM|CHURCH|SCHOOL|UNIVERSITY|HOSPITAL|FOUNDATION|CONGREGATION|"
    # Placeholder names
    r"UNAVAILABLE|UNKNOWN)\b",
    re.IGNORECASE,
)

# Regex to detect when an owner name is really a street address or starts
# with a number (e.g., "145 READE STREET", "33 EAST 69TH STREETCOMPANY",
# "145 READE", "73RD SELZ")
_ADDRESS_AS_NAME = re.compile(
    r"^\d+\s+",  # anything starting with digits + space
    re.IGNORECASE,
)

# Additional junk patterns: names that are clearly not people but slip past
# the entity regex (diplomatic missions, abbreviated government names, etc.)
_JUNK_NAME_PATTERNS = re.compile(
    r"\b(MISSION|HEIGHTS|FRONTIER|CENTURY|RUSSIAN|PEOPLES|"
    r"REPUB|FEDERAL|NATIONAL|ROYAL|FOREIGN|GENERAL|"
    r"SOCIETY|ASSOCIATION|CLUB|BOARD|COUNCIL|COMMITTEE|"
    r"OF THE|OF NEW|PNR)\b",
    re.IGNORECASE,
)

# PLUTO uses text borough codes, but ACRIS uses numeric codes.
# This map translates so ACRIS queries work correctly.
_PLUTO_BOROUGH_TO_ACRIS: dict[str, str] = {
    "MN": "1",  # Manhattan
    "BX": "2",  # Bronx
    "BK": "3",  # Brooklyn
    "QN": "4",  # Queens
    "SI": "5",  # Staten Island
}

# Residential building class prefixes — these get a confidence bonus because
# a person living in a $5M home is a better luxury service lead than a
# company owning a $5M office building.
_RESIDENTIAL_CLASS_PREFIXES = ("A", "B", "C", "D", "R", "S")

# Mapping from building class first letter to NYC tax class.
# A/B = 1-3 family homes (tax class 1), C/D/R/S = multi-family/condos (tax class 2),
# everything else = commercial (tax class 4).
_BLDGCLASS_TO_TAXCLASS: dict[str, str] = {
    "A": "1", "B": "1",                       # 1-3 family homes
    "C": "2", "D": "2", "R": "2", "S": "2",   # apartments, condos, mixed
}


def _derive_tax_class(building_class: str) -> str:
    """Derive the NYC tax class from a PLUTO building class code.

    PLUTO doesn't expose tax class directly, but we can infer it from the
    building class letter: A/B = single-family (class 1), C/D/R/S = multi-
    family (class 2), everything else = commercial (class 4).

    Args:
        building_class: PLUTO building class code (e.g., "A5", "R4", "O5").

    Returns:
        Tax class string: "1", "2", or "4".
    """
    if not building_class:
        return "4"
    first_letter = building_class[0].upper()
    return _BLDGCLASS_TO_TAXCLASS.get(first_letter, "4")


def _parse_int(value) -> Optional[int]:
    """Safely convert a PLUTO field value to int, returning None on failure.

    PLUTO returns numbers as strings (e.g., "3", "1920", "2500.0"). This
    helper handles strings, floats, and None without crashing.
    """
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


# NYC building class descriptions — maps the first 1-2 characters of a PLUTO
# building class code to a human-readable property type. These come from the
# NYC Department of Finance building classification system.
_BUILDING_TYPE_DESCRIPTIONS: dict[str, str] = {
    "A0": "One Family Cape Cod",
    "A1": "One Family Detached",
    "A2": "One Family Attached",
    "A3": "One Family Semi-Detached",
    "A4": "One Family Artist Residence",
    "A5": "One Family Attached",
    "A6": "One Family Mansion",
    "A7": "One Family Detached",
    "A8": "One Family Bungalow",
    "A9": "One Family",
    "B1": "Two Family Brick",
    "B2": "Two Family Frame",
    "B3": "Two Family Converted",
    "B9": "Two Family",
    "C0": "Walk-Up Apartment",
    "C1": "Walk-Up Apartment (over 6 units)",
    "C2": "Walk-Up Apartment (3-5 units, frame)",
    "C3": "Walk-Up Apartment (4+ units)",
    "C4": "Walk-Up Apartment (old law tenement)",
    "C5": "Walk-Up Apartment (converted)",
    "C6": "Walk-Up Apartment (cooperative)",
    "C7": "Walk-Up Apartment (over 6 units)",
    "C8": "Walk-Up Apartment (co-op, converted)",
    "C9": "Walk-Up Apartment (garden apartment)",
    "D0": "Elevator Apartment",
    "D1": "Elevator Apartment (semi-fireproof)",
    "D2": "Elevator Apartment (artist-in-residence)",
    "D3": "Elevator Apartment (fireproof)",
    "D4": "Elevator Apartment (cooperative)",
    "D5": "Elevator Apartment (converted)",
    "D6": "Elevator Apartment (fireproof, co-op)",
    "D7": "Elevator Apartment (semi-fireproof, co-op)",
    "D8": "Elevator Apartment (luxury)",
    "D9": "Elevator Apartment (co-op, misc)",
    "R1": "Condo (residential unit)",
    "R2": "Condo (residential unit)",
    "R3": "Condo (residential unit, homeowner)",
    "R4": "Condo (residential unit)",
    "R6": "Condo (residential unit, co-op)",
    "R9": "Condo (residential unit, misc)",
    "S0": "Mixed Residential/Commercial",
    "S1": "Mixed Residential/Commercial (primarily residential)",
    "S2": "Mixed Residential/Commercial (primarily commercial)",
    "S3": "Mixed Residential/Commercial (3+ units)",
    "S4": "Mixed Residential/Commercial (co-op)",
    "S5": "Mixed Residential/Commercial (converted)",
    "S9": "Mixed Residential/Commercial (misc)",
}

# Broader fallback descriptions when exact code isn't in the detailed map
_BUILDING_CLASS_LETTER_DESCRIPTIONS: dict[str, str] = {
    "A": "One Family Home",
    "B": "Two Family Home",
    "C": "Walk-Up Apartment",
    "D": "Elevator Apartment",
    "R": "Condo",
    "S": "Mixed Residential/Commercial",
}


def _get_building_type_description(building_class: str) -> Optional[str]:
    """Map a PLUTO building class code to a human-readable property type.

    Tries the full code first (e.g., "A5" → "One Family Attached"), then
    falls back to the first letter (e.g., "A" → "One Family Home").

    Args:
        building_class: PLUTO building class code (e.g., "A5", "R4", "D8").

    Returns:
        Human-readable description, or None if unrecognized.
    """
    if not building_class:
        return None
    code = building_class.strip().upper()
    if code in _BUILDING_TYPE_DESCRIPTIONS:
        return _BUILDING_TYPE_DESCRIPTIONS[code]
    if code[0] in _BUILDING_CLASS_LETTER_DESCRIPTIONS:
        return _BUILDING_CLASS_LETTER_DESCRIPTIONS[code[0]]
    return None


def _estimate_market_value(assessed_total: float, building_class: str) -> float:
    """Estimate true market value from NYC assessed value and building class.

    NYC assesses properties at a fraction of their real market value. The
    fraction depends on the tax class, which we derive from the building
    class code. We multiply back up to get a rough estimate of what the
    property would sell for.

    Args:
        assessed_total: The city's assessed total value in USD.
        building_class: PLUTO building class code (e.g., "A5", "R4").

    Returns:
        Estimated market value in USD.
    """
    tax_class = _derive_tax_class(building_class)
    multiplier = TAX_CLASS_MULTIPLIERS.get(tax_class, 2.22)
    return assessed_total * multiplier


def _parse_owner_name(raw_name: str) -> tuple[str, str, bool]:
    """Parse a PLUTO owner name into (first_name, last_name, is_llc).

    Owner names in PLUTO come in all-caps and in various formats:
    - "SMITH, JOHN" or "SMITH JOHN" (individuals)
    - "123 BROADWAY LLC" or "ACME HOLDINGS INC" (companies)

    For companies, we store the company name in last_name and flag is_llc=True
    so downstream processes know to do identity enrichment.

    Args:
        raw_name: Raw owner name string from PLUTO.

    Returns:
        Tuple of (first_name, last_name, is_llc).
    """
    if not raw_name or not raw_name.strip():
        return ("Unknown", "Unknown", False)

    cleaned = raw_name.strip()

    # Check if this is an LLC/corporation/trust/institution
    if _ENTITY_PATTERNS.search(cleaned):
        return ("", cleaned.title(), True)

    # Check if the "name" is actually a street address or starts with a number
    if _ADDRESS_AS_NAME.search(cleaned):
        return ("", cleaned.title(), True)

    # Catch diplomatic, organizational, and other junk names
    if _JUNK_NAME_PATTERNS.search(cleaned):
        return ("", cleaned.title(), True)

    # Single-word names that are clearly country names or not people
    if cleaned.upper() in ("IRAN", "IRAQ", "CHINA", "JAPAN", "ITALY", "FRANCE"):
        return ("", cleaned.title(), True)

    # Strip "AS TRUSTEE", "AS EXECUTOR" etc. — these are role markers, not names
    cleaned = re.sub(r",?\s*AS\s+(TRUSTEE|EXECUTOR|AGENT|CUSTODIAN).*$", "", cleaned, flags=re.IGNORECASE).strip()

    # If stripping the role marker left nothing (e.g., name was "AS TRUSTEE")
    if not cleaned:
        return ("Unknown", "Unknown", False)

    # Handle "LAST, FIRST" format (common in property records) — most reliable
    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",", 1)]
        last_name = parts[0].title()
        first_name = parts[1].split()[0].title() if parts[1].strip() else ""
        return (first_name, last_name, False)

    # Space-separated names without a comma. In PLUTO these are typically
    # "LAST FIRST" or "LAST FIRST MIDDLE" — but are less reliable than
    # comma-separated names.
    parts = cleaned.split()
    if len(parts) == 1:
        return (parts[0].title(), "", False)

    # Assume LAST FIRST (tax record convention)
    return (parts[1].title(), parts[0].title(), False)


def _calculate_confidence(
    market_value: float,
    is_llc: bool,
    building_class: str,
) -> float:
    """Score lead confidence from 0.0 to 1.0.

    Higher property value = higher confidence (more wealth signal).
    LLC ownership reduces confidence (we don't know the actual person yet).
    Residential building classes get a bonus (better luxury service fit).

    Args:
        market_value: Estimated market value in USD.
        is_llc: Whether the owner is an LLC/corporation.
        building_class: PLUTO building class code (e.g., "A5", "R4").

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    score = 0.0

    # Market value tiers
    if market_value >= 10_000_000:
        score += 0.5
    elif market_value >= 5_000_000:
        score += 0.4
    elif market_value >= 2_000_000:
        score += 0.3
    elif market_value >= 1_000_000:
        score += 0.2

    # Residential building class bonus
    if building_class and building_class[0] in _RESIDENTIAL_CLASS_PREFIXES:
        score += 0.2

    # LLC penalty — we can't verify the person behind it
    if is_llc:
        score -= 0.15

    # Baseline: we have address + value data from a verified public source
    score += 0.1

    return max(0.0, min(score, 1.0))


def _build_discovery_trigger(
    owner_name: str,
    address: str,
    market_value: float,
    neighborhood: str,
) -> str:
    """Create a human-readable trigger string for the lead card.

    Args:
        owner_name: Display name of the property owner.
        address: Street address of the property.
        market_value: Estimated market value in USD.
        neighborhood: Neighborhood name or zip code area.

    Returns:
        A sentence like "John Smith owns $8.2M property at 123 W 10th St, West Village"
    """
    if market_value >= 1_000_000:
        value_display = f"${market_value / 1_000_000:.1f}M"
    else:
        value_display = f"${market_value:,.0f}"

    return f"{owner_name} owns {value_display} property at {address}, {neighborhood}"


def _build_address(record: dict) -> str:
    """Clean up the address from a PLUTO record.

    PLUTO's `address` field contains the full street address in all-caps
    (e.g., "49 DOWNING STREET"). We just title-case it for display.

    Args:
        record: A single PLUTO record dict from the SODA API.

    Returns:
        Formatted street address string.
    """
    raw = record.get("address", "").strip()
    if raw:
        return raw.title()
    return "Unknown Address"


def _zip_to_neighborhood(zip_code: str) -> str:
    """Look up which neighborhood a zip code belongs to.

    Args:
        zip_code: A 5-digit NYC zip code.

    Returns:
        Neighborhood name, or "NYC" if not in our presets.
    """
    for neighborhood, zips in NEIGHBORHOOD_ZIP_CODES.items():
        if zip_code in zips:
            return neighborhood
    return "NYC"


def _get_condo_building_bbls(
    zip_codes: list[str],
    client: Socrata,
    limit: int = 200,
    min_market_value: float = 1_000_000.0,
    individuals_only: bool = False,
) -> tuple[list[tuple[str, str]], dict[str, str], dict[str, str], dict[str, float], list[Lead]]:
    """Query PLUTO for condo/co-op/apartment buildings and return BBL pairs + building owner leads.

    Condo and apartment buildings have building classes starting with R, C, D,
    or S. We pull their borough and block so the ACRIS engine can look up
    individual unit owners from deed records. We also process the building-
    level owner names directly — people who own entire apartment buildings
    are high-value leads that ACRIS wouldn't find (ACRIS only finds unit buyers).

    Args:
        zip_codes: List of NYC zip codes to search.
        client: Socrata client instance (reuse from fetch_properties).
        limit: Max records per zip code.
        min_market_value: Minimum estimated market value to qualify.
        individuals_only: If True, skip LLC/entity building owners.

    Returns:
        Tuple of:
        - borough_block_pairs: Unique (borough, block) tuples for ACRIS
        - bbl_zip_lookup: Maps "borough-block" to zip code
        - bbl_address_lookup: Maps "borough-block" to building address
        - bbl_value_lookup: Maps "borough-block" to estimated market value
        - building_leads: Lead objects for building-level owners from PLUTO
    """
    borough_block_pairs: list[tuple[str, str]] = []
    bbl_zip_lookup: dict[str, str] = {}
    bbl_address_lookup: dict[str, str] = {}
    bbl_value_lookup: dict[str, float] = {}
    building_leads: list[Lead] = []
    seen_blocks: set[str] = set()

    for zip_code in zip_codes:
        try:
            where_clause = (
                f"zipcode='{zip_code}' AND assesstot > 0 AND "
                f"(bldgclass LIKE 'R%' OR bldgclass LIKE 'C%' "
                f"OR bldgclass LIKE 'D%' OR bldgclass LIKE 'S%')"
            )
            records = client.get(
                PLUTO_RESOURCE_ID,
                where=where_clause,
                select=(
                    "ownername,borough,block,lot,address,assesstot,"
                    "bldgclass,zipcode,yearbuilt,lotarea,numfloors,bldgarea"
                ),
                limit=limit,
                order="assesstot DESC",
            )

            for record in records:
                raw_borough = record.get("borough", "")
                block = record.get("block", "")
                if not raw_borough or not block:
                    continue

                # Convert PLUTO text codes (MN, BK) to ACRIS numeric (1, 3)
                borough = _PLUTO_BOROUGH_TO_ACRIS.get(raw_borough, raw_borough)

                bb_key = f"{borough}-{block}"
                if bb_key in seen_blocks:
                    continue
                seen_blocks.add(bb_key)

                borough_block_pairs.append((borough, block))
                bbl_zip_lookup[bb_key] = zip_code

                address = record.get("address", "").strip().title()
                if address:
                    bbl_address_lookup[bb_key] = address

                assessed_total = float(record.get("assesstot", 0))
                building_class = record.get("bldgclass", "")
                market_value = _estimate_market_value(assessed_total, building_class)
                bbl_value_lookup[bb_key] = market_value

                # Also process this building's owner as a lead directly.
                # This catches people who own entire apartment buildings —
                # high-value leads that ACRIS unit searches won't find.
                try:
                    lead = _process_property_record(
                        record, zip_code, min_market_value
                    )
                    if lead is not None:
                        if not (individuals_only and lead.company is not None):
                            building_leads.append(lead)
                except Exception:
                    pass  # Don't let one bad record block the BBL collection

        except Exception as exc:
            logger.warning(
                "Failed to query PLUTO condo buildings for zip %s: %s",
                zip_code,
                exc,
            )

    logger.info(
        "Found %d unique condo/co-op building blocks and %d building owner leads across %d zip codes",
        len(borough_block_pairs),
        len(building_leads),
        len(zip_codes),
    )

    return borough_block_pairs, bbl_zip_lookup, bbl_address_lookup, bbl_value_lookup, building_leads


def fetch_properties(
    zip_codes: list[str],
    min_market_value: float = 1_000_000.0,
    limit: int = 200,
    residential_only: bool = True,
    individuals_only: bool = False,
    include_condos: bool = False,
    app_token: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> list[Lead]:
    """Query NYC PLUTO for high-value properties and return qualified leads.

    This is the main entry point for the Real Estate engine. It connects to
    NYC's open data portal, pulls property records for the requested zip codes,
    filters by estimated market value, and packages qualifying properties as
    Lead objects.

    Args:
        zip_codes: List of NYC zip codes to search (e.g., ["10014", "10013"]).
        min_market_value: Minimum estimated market value to qualify (default $1M).
        limit: Maximum number of results to return per zip code.
        residential_only: If True (default), only search building classes A and B
                         (1-3 family homes, brownstones, townhouses). These are
                         the properties actual people own and live in. Set to
                         False to include commercial, apartments, condos, etc.
        individuals_only: If True, filter out LLCs, corporations, trusts, and
                         institutions — only return leads with actual human
                         names. Default False (show everything).
        include_condos: If True, also query ACRIS deed records to find individual
                       condo/co-op unit owners. This is slower (3 API calls per
                       building block) but discovers owners that PLUTO misses.
        app_token: Optional Socrata app token for higher rate limits.
                   Works fine without one, just slower if you make lots of queries.
        progress_callback: Optional function(completed, total) for ACRIS progress.

    Returns:
        List of Lead objects for property owners meeting the value threshold.
    """
    logger.info(
        "Real Estate scan starting | zips=%s | min_value=$%s | limit=%d | "
        "residential_only=%s | individuals_only=%s",
        zip_codes,
        f"{min_market_value:,.0f}",
        limit,
        residential_only,
        individuals_only,
    )

    # Deduplicate zip codes — multiple neighborhoods can share the same zip
    zip_codes = list(dict.fromkeys(zip_codes))

    client = Socrata(SOCRATA_DOMAIN, app_token)
    leads: list[Lead] = []
    total_scanned = 0
    errors = 0
    last_error = None

    for zip_code in zip_codes:
        try:
            # Build the WHERE clause
            where_clause = f"zipcode='{zip_code}' AND assesstot > 0"
            if residential_only:
                # A = one-family, B = two-family — these are homes people
                # actually live in (brownstones, townhouses)
                where_clause += " AND (bldgclass LIKE 'A%' OR bldgclass LIKE 'B%')"

            records = client.get(
                PLUTO_RESOURCE_ID,
                where=where_clause,
                select=(
                    "ownername,address,zipcode,borough,"
                    "assesstot,bldgclass,yearbuilt,lotarea,"
                    "numfloors,bldgarea"
                ),
                limit=limit,
                order="assesstot DESC",
            )

            total_scanned += len(records)

            for record in records:
                try:
                    lead = _process_property_record(
                        record, zip_code, min_market_value
                    )
                    if lead is None:
                        continue
                    # Skip entities/LLCs if user only wants named individuals
                    if individuals_only and lead.company is not None:
                        continue
                    leads.append(lead)
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "Failed to parse property record in zip %s: %s",
                        zip_code,
                        exc,
                    )

        except Exception as exc:
            errors += 1
            last_error = exc
            logger.error(
                "Failed to query PLUTO for zip %s: %s", zip_code, exc
            )

    # --- ACRIS condo/co-op owner lookup (opt-in) ---
    if include_condos:
        from src.engines import acris  # Lazy import to avoid circular dependency

        logger.info("Condo mode enabled — querying PLUTO for condo buildings...")
        try:
            bb_pairs, zip_lookup, addr_lookup, val_lookup, bldg_leads = (
                _get_condo_building_bbls(
                    zip_codes, client, limit,
                    min_market_value=min_market_value,
                    individuals_only=individuals_only,
                )
            )
            # Add building-level owners (people who own entire buildings)
            if bldg_leads:
                logger.info(
                    "PLUTO returned %d building-level owner leads", len(bldg_leads)
                )
                leads.extend(bldg_leads)
            if bb_pairs:
                condo_leads = acris.fetch_condo_unit_owners(
                    borough_block_pairs=bb_pairs,
                    bbl_zip_lookup=zip_lookup,
                    bbl_address_lookup=addr_lookup,
                    bbl_value_lookup=val_lookup,
                    min_sale_value=min_market_value,
                    limit_per_block=limit,
                    app_token=app_token,
                    progress_callback=progress_callback,
                )
                logger.info("ACRIS returned %d condo unit leads", len(condo_leads))
                leads.extend(condo_leads)
        except Exception as exc:
            logger.error("ACRIS condo lookup failed: %s", exc)

    client.close()

    logger.info(
        "Real Estate scan complete | records_scanned=%d | leads_found=%d | errors=%d",
        total_scanned,
        len(leads),
        errors,
    )

    # If every single zip failed, surface the error so the UI can show it
    if errors == len(zip_codes) and last_error is not None:
        raise RuntimeError(
            f"All {errors} zip code queries failed. Last error: {last_error}"
        )

    return leads


def _process_property_record(
    record: dict,
    zip_code: str,
    min_market_value: float,
) -> Optional[Lead]:
    """Parse one PLUTO property record and return a Lead if it qualifies.

    Returns None if the property doesn't meet the market value threshold.
    """
    assessed_total = float(record.get("assesstot", 0))
    building_class = record.get("bldgclass", "")

    market_value = _estimate_market_value(assessed_total, building_class)

    if market_value < min_market_value:
        return None

    raw_name = record.get("ownername", "")
    first_name, last_name, is_llc = _parse_owner_name(raw_name)

    address = _build_address(record)
    neighborhood = _zip_to_neighborhood(zip_code)

    owner_display = f"{first_name} {last_name}".strip() if not is_llc else last_name
    trigger = _build_discovery_trigger(
        owner_display, address, market_value, neighborhood
    )

    confidence = _calculate_confidence(market_value, is_llc, building_class)

    return Lead(
        first_name=first_name,
        last_name=last_name,
        address=address,
        city="New York",
        state="NY",
        zip_code=zip_code,
        company=last_name if is_llc else None,
        estimated_wealth=market_value,
        discovery_trigger=trigger,
        source=LeadSource.TAX_ASSESSOR,
        confidence_score=confidence,
        year_built=_parse_int(record.get("yearbuilt")),
        num_floors=_parse_int(record.get("numfloors")),
        building_area=_parse_int(record.get("bldgarea")),
        lot_area=_parse_int(record.get("lotarea")),
        building_type=_get_building_type_description(building_class),
    )
