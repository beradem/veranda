"""ACRIS Engine — NYC deed registry for condo/co-op unit owner discovery.

PLUTO tells us about buildings, but for condos and co-ops it only shows the
building-level owner (an LLC or condo association). ACRIS (Automated City
Register Information System) records every deed transfer — so when someone
buys Unit 42A, their name is in ACRIS.

This engine queries three ACRIS tables (all on the same NYC Open Data / Socrata
API we already use for PLUTO) and joins them in Python to find the current
owner of each condo unit:

1. Real Property Legals  — links documents to physical locations (borough/block/lot/unit)
2. Real Property Master   — document details (type, date, amount)
3. Real Property Parties  — buyer/seller names on each document

No new dependencies needed — uses the same sodapy client as real_estate.py.

Performance: blocks are processed in parallel (ThreadPoolExecutor) and legals
queries are batched (multiple blocks per API call) to minimize total round-trips.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from sodapy import Socrata

from src.models.lead import Lead, LeadSource
from src.engines.real_estate import (
    _parse_owner_name,
    _calculate_confidence,
    _zip_to_neighborhood,
)

logger = logging.getLogger(__name__)

# --- ACRIS Socrata resource IDs ---
ACRIS_MASTER_ID = "bnx9-e6tj"
ACRIS_PARTIES_ID = "636b-3b5g"
ACRIS_LEGALS_ID = "8h5j-fqxa"

# Deed document types that indicate an ownership transfer
DEED_DOC_TYPES = ("DEED", "DEED, RC", "CORRD", "DEED, LE", "IDED")

# Party type 2 = Grantee/Buyer (the person who now owns the property)
PARTY_TYPE_BUYER = "2"

# ACRIS property_type codes for condos and co-ops.
# SC (sub-condo) is the dominant type (~93% of condo records).
# AP (apartment), CC (condo), CP (co-op) cover the rest.
CONDO_PROPERTY_TYPES = ("SC", "AP", "CC", "CP", "SP")

# How many blocks to combine into a single legals query.
# Kept small because condo-heavy blocks (SC type) can have thousands of
# records each — batching too many together causes API timeouts.
LEGALS_BATCH_SIZE = 3

# How many block groups to process in parallel
MAX_WORKERS = 5


def _batch_query(
    client: Socrata,
    resource_id: str,
    id_field: str,
    ids: list[str],
    select: str,
    where_extra: str = "",
    batch_size: int = 50,
) -> list[dict]:
    """Query a Socrata dataset in batches using WHERE id IN (...).

    Socrata has URL length limits, so we can't send thousands of IDs at once.
    This helper splits the IDs into groups and combines the results.

    Args:
        client: Socrata client instance.
        resource_id: Dataset resource ID.
        id_field: Column name to filter on (e.g., "document_id").
        ids: List of values to look up.
        select: Comma-separated columns to return.
        where_extra: Additional WHERE conditions (ANDed with the IN clause).
        batch_size: How many IDs per query (default 50).

    Returns:
        Combined list of result dicts from all batches.
    """
    results: list[dict] = []
    unique_ids = list(dict.fromkeys(ids))

    for i in range(0, len(unique_ids), batch_size):
        batch = unique_ids[i : i + batch_size]
        in_clause = ", ".join(f"'{doc_id}'" for doc_id in batch)
        where = f"{id_field} IN ({in_clause})"
        if where_extra:
            where = f"{where} AND {where_extra}"

        try:
            rows = client.get(
                resource_id,
                where=where,
                select=select,
                limit=5000,
            )
            results.extend(rows)
        except Exception as exc:
            logger.warning(
                "ACRIS batch query failed for %s (batch %d): %s",
                resource_id,
                i // batch_size,
                exc,
            )

    return results


def _query_legals_batch(
    client: Socrata,
    borough: str,
    blocks: list[str],
) -> list[dict]:
    """Get ACRIS legal records for multiple blocks in a single API call.

    Instead of querying one block at a time, we combine blocks using
    block IN ('601','602','603',...) — fewer API round-trips = faster.

    Args:
        client: Socrata client instance.
        borough: NYC borough code (1=Manhattan, 2=Bronx, etc.).
        blocks: List of tax block numbers to query together.

    Returns:
        List of legal record dicts for all blocks in the batch.
    """
    prop_type_filter = " OR ".join(
        f"property_type='{pt}'" for pt in CONDO_PROPERTY_TYPES
    )
    block_in = ", ".join(f"'{b}'" for b in blocks)
    where = (
        f"borough='{borough}' AND block IN ({block_in}) "
        f"AND ({prop_type_filter})"
    )

    try:
        records = client.get(
            ACRIS_LEGALS_ID,
            where=where,
            select="document_id,borough,block,lot,unit",
            limit=50000,
        )
        return records
    except Exception as exc:
        logger.warning(
            "ACRIS legals batch query failed for borough=%s blocks=%s: %s",
            borough,
            blocks,
            exc,
        )
        return []


def _query_legals_by_borough_block(
    client: Socrata,
    borough: str,
    block: str,
) -> list[dict]:
    """Get ACRIS legal records for a single block (kept for tests/backwards compat)."""
    return _query_legals_batch(client, borough, [block])


def _query_master_deeds(
    client: Socrata,
    document_ids: list[str],
) -> list[dict]:
    """Get deed documents from the ACRIS Master table.

    Filters to deed-type documents only (DEED, DEED RC, CORRD, etc.) so we
    skip mortgages, liens, and other non-ownership records.

    Args:
        client: Socrata client instance.
        document_ids: List of document IDs from the Legals table.

    Returns:
        List of master record dicts with document_id, doc_type, document_date,
        document_amt fields.
    """
    if not document_ids:
        return []

    doc_type_filter = " OR ".join(
        f"doc_type='{dt}'" for dt in DEED_DOC_TYPES
    )
    where_extra = f"({doc_type_filter})"

    return _batch_query(
        client=client,
        resource_id=ACRIS_MASTER_ID,
        id_field="document_id",
        ids=document_ids,
        select="document_id,doc_type,document_date,document_amt",
        where_extra=where_extra,
    )


def _query_buyer_parties(
    client: Socrata,
    document_ids: list[str],
) -> list[dict]:
    """Get buyer names from the ACRIS Parties table.

    Filters to party_type='2' (grantee/buyer) — the person who received
    ownership of the property.

    Args:
        client: Socrata client instance.
        document_ids: List of document IDs from the Master table.

    Returns:
        List of party record dicts with document_id, party_type, name fields.
    """
    if not document_ids:
        return []

    return _batch_query(
        client=client,
        resource_id=ACRIS_PARTIES_ID,
        id_field="document_id",
        ids=document_ids,
        select="document_id,party_type,name",
        where_extra=f"party_type='{PARTY_TYPE_BUYER}'",
    )


def _find_current_owner_per_unit(
    legals: list[dict],
    masters: list[dict],
) -> dict[str, tuple[dict, dict]]:
    """For each unique condo unit (BBL+unit), find the most recent deed.

    The buyer on the most recent deed is the current owner. This handles the
    common case where a unit has been sold multiple times — we only care about
    the latest transaction.

    Args:
        legals: ACRIS legal records (document_id, borough, block, lot, unit).
        masters: ACRIS master records filtered to deeds (document_id, document_date, document_amt).

    Returns:
        Dict mapping "borough-block-lot-unit" to (legal_record, master_record)
        for the most recent deed.
    """
    # Index masters by document_id for fast lookup
    master_by_doc: dict[str, dict] = {}
    for master in masters:
        doc_id = master.get("document_id", "")
        if doc_id:
            master_by_doc[doc_id] = master

    # For each unit, find the most recent deed
    best_per_unit: dict[str, tuple[dict, dict]] = {}

    for legal in legals:
        doc_id = legal.get("document_id", "")
        master = master_by_doc.get(doc_id)
        if not master:
            continue

        borough = legal.get("borough", "")
        block = legal.get("block", "")
        lot = legal.get("lot", "")
        unit = legal.get("unit", "")
        unit_key = f"{borough}-{block}-{lot}-{unit}"

        doc_date = master.get("document_date", "")
        existing = best_per_unit.get(unit_key)

        if existing is None:
            best_per_unit[unit_key] = (legal, master)
        else:
            existing_date = existing[1].get("document_date", "")
            if doc_date > existing_date:
                best_per_unit[unit_key] = (legal, master)

    return best_per_unit


def _build_acris_lead(
    party: dict,
    legal: dict,
    master: dict,
    zip_code: str,
    building_address: str = "",
    assessed_value: float = 0.0,
    building_units: int = 0,
) -> Optional[Lead]:
    """Convert ACRIS records into a Lead object.

    Uses the buyer name from the Parties table, location from Legals, and
    sale details from Master to build a complete lead. Reuses _parse_owner_name
    from the real_estate engine for consistent name parsing.

    Args:
        party: ACRIS party record (name, party_type).
        legal: ACRIS legal record (borough, block, lot, unit).
        master: ACRIS master record (document_date, document_amt).
        zip_code: Zip code of the building (from PLUTO).
        building_address: Street address of the building (from PLUTO).
        assessed_value: PLUTO assessed market value (fallback for $0 deeds).
        building_units: Number of residential units in the building (from PLUTO).
                       Used to estimate per-unit value when deed amount is $0.

    Returns:
        A Lead object, or None if the record should be skipped.
    """
    raw_name = party.get("name", "")
    first_name, last_name, is_llc = _parse_owner_name(raw_name)

    # Skip entities — we want named individuals
    if is_llc:
        return None

    # Determine the value to use
    sale_amount = 0.0
    try:
        sale_amount = float(master.get("document_amt", 0))
    except (ValueError, TypeError):
        pass

    # Use sale amount if available, otherwise estimate per-unit value
    # by dividing the building's total assessed value by unit count.
    if sale_amount > 0:
        wealth_value = sale_amount
    elif building_units > 0:
        wealth_value = assessed_value / building_units
    else:
        wealth_value = assessed_value

    # Skip if both sale amount and assessed value are $0
    if wealth_value <= 0:
        return None

    unit = legal.get("unit", "")
    neighborhood = _zip_to_neighborhood(zip_code)

    # Build the address with unit number
    address = building_address
    if address and unit:
        address = f"{address}, Unit {unit}"
    elif not address:
        address = "Unknown Address"

    # Discovery trigger
    owner_display = f"{first_name} {last_name}".strip()
    if wealth_value >= 1_000_000:
        value_display = f"${wealth_value / 1_000_000:.1f}M"
    else:
        value_display = f"${wealth_value:,.0f}"

    deed_date = master.get("document_date", "")
    if deed_date:
        # Truncate to date portion (ACRIS dates can have timestamps)
        deed_date = deed_date[:10]

    trigger_parts = [
        f"{owner_display} purchased {value_display} condo unit"
    ]
    if unit:
        trigger_parts[0] += f" (Unit {unit})"
    if building_address:
        trigger_parts.append(f"at {building_address}")
    trigger_parts.append(neighborhood)
    if deed_date:
        trigger_parts.append(f"on {deed_date}")
    trigger = ", ".join(trigger_parts)

    confidence = _calculate_confidence(
        market_value=wealth_value,
        is_llc=False,
        building_class="R4",  # Treat all condo units as R4 for scoring
    )

    return Lead(
        first_name=first_name,
        last_name=last_name,
        address=address,
        city="New York",
        state="NY",
        zip_code=zip_code,
        estimated_wealth=wealth_value,
        discovery_trigger=trigger,
        source=LeadSource.TAX_ASSESSOR,
        confidence_score=confidence,
        building_type="Condo Unit",
        unit_number=unit if unit else None,
        deed_sale_amount=sale_amount if sale_amount > 0 else None,
        deed_date=deed_date if deed_date else None,
    )


def _process_block_group(
    client: Socrata,
    borough: str,
    blocks: list[str],
    bbl_zip_lookup: dict[str, str],
    bbl_address_lookup: dict[str, str],
    bbl_value_lookup: dict[str, float],
    bbl_units_lookup: dict[str, int],
    min_sale_value: float,
    limit_per_block: int,
) -> list[Lead]:
    """Process a batch of blocks in one borough: legals → masters → parties → leads.

    This is the unit of work that gets run in parallel. Each call handles
    multiple blocks (combined into one legals query) and returns leads.

    Args:
        client: Socrata client (thread-safe for reads).
        borough: Numeric borough code.
        blocks: List of block numbers to process together.
        bbl_zip_lookup: Maps "borough-block" to zip code.
        bbl_address_lookup: Maps "borough-block" to building address.
        bbl_value_lookup: Maps "borough-block" to assessed market value.
        bbl_units_lookup: Maps "borough-block" to total unit count.
        min_sale_value: Minimum value threshold for leads.
        limit_per_block: Max leads per block.

    Returns:
        List of Lead objects found in this block group.
    """
    leads: list[Lead] = []

    # Step 1: Get legal records for all blocks in this batch at once
    legals = _query_legals_batch(client, borough, blocks)
    if not legals:
        return leads

    # Extract unique document IDs
    doc_ids = list({
        leg.get("document_id", "")
        for leg in legals
        if leg.get("document_id")
    })

    # Step 2: Filter to deed documents only
    masters = _query_master_deeds(client, doc_ids)
    if not masters:
        return leads

    # Step 3: Find current owner per unit (most recent deed)
    unit_owners = _find_current_owner_per_unit(legals, masters)

    # Get the document IDs for the winning deeds
    winning_doc_ids = list({
        master.get("document_id", "")
        for _, master in unit_owners.values()
        if master.get("document_id")
    })

    # Step 4: Get buyer names
    parties = _query_buyer_parties(client, winning_doc_ids)

    # Index parties by document_id
    parties_by_doc: dict[str, list[dict]] = {}
    for party in parties:
        doc_id = party.get("document_id", "")
        if doc_id:
            parties_by_doc.setdefault(doc_id, []).append(party)

    # Step 5: Build leads, tracking count per block
    block_lead_counts: dict[str, int] = {}

    for unit_key, (legal, master) in unit_owners.items():
        block = legal.get("block", "")
        block_lead_counts.setdefault(block, 0)
        if block_lead_counts[block] >= limit_per_block:
            continue

        doc_id = master.get("document_id", "")
        unit_parties = parties_by_doc.get(doc_id, [])

        bb_key = f"{borough}-{block}"
        zip_code = bbl_zip_lookup.get(bb_key, "")
        building_address = bbl_address_lookup.get(bb_key, "")
        assessed_value = bbl_value_lookup.get(bb_key, 0.0)
        building_units = bbl_units_lookup.get(bb_key, 0)

        for party in unit_parties:
            lead = _build_acris_lead(
                party=party,
                legal=legal,
                master=master,
                zip_code=zip_code,
                building_address=building_address,
                assessed_value=assessed_value,
                building_units=building_units,
            )
            if lead is None:
                continue

            if min_sale_value > 0 and (lead.estimated_wealth or 0) < min_sale_value:
                continue

            leads.append(lead)
            block_lead_counts[block] += 1

    return leads


def fetch_condo_unit_owners(
    borough_block_pairs: list[tuple[str, str]],
    bbl_zip_lookup: dict[str, str],
    bbl_address_lookup: dict[str, str],
    bbl_value_lookup: dict[str, float],
    bbl_units_lookup: Optional[dict[str, int]] = None,
    min_sale_value: float = 0.0,
    limit_per_block: int = 200,
    app_token: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[Lead]:
    """Find individual condo/co-op unit owners via ACRIS deed records.

    This is the main entry point for the ACRIS engine. It takes borough+block
    pairs (from PLUTO condo buildings) and returns Lead objects for individual
    unit buyers.

    Performance optimizations:
    - Blocks in the same borough are grouped and queried together (fewer API calls)
    - Groups are processed in parallel using ThreadPoolExecutor
    - Progress callback lets the UI show a progress bar

    Args:
        borough_block_pairs: List of (borough_code, block_number) from PLUTO.
        bbl_zip_lookup: Maps "borough-block" to zip code.
        bbl_address_lookup: Maps "borough-block" to building street address.
        bbl_value_lookup: Maps "borough-block" to PLUTO assessed market value.
        bbl_units_lookup: Maps "borough-block" to total unit count. Used to
                         estimate per-unit value when deed amount is $0.
        min_sale_value: Minimum deed sale amount to qualify (default $0 = all).
        limit_per_block: Max leads per block.
        app_token: Optional Socrata app token.
        progress_callback: Optional function(completed, total) called after each
                          block group finishes. Use this for progress bars.

    Returns:
        List of Lead objects for individual condo unit owners.
    """
    if bbl_units_lookup is None:
        bbl_units_lookup = {}
    logger.info(
        "ACRIS scan starting | blocks=%d | min_sale=$%s",
        len(borough_block_pairs),
        f"{min_sale_value:,.0f}",
    )

    # Group blocks by borough so we can batch legals queries
    borough_groups: dict[str, list[str]] = {}
    for borough, block in borough_block_pairs:
        borough_groups.setdefault(borough, []).append(block)

    # Split each borough's blocks into batches of LEGALS_BATCH_SIZE
    work_items: list[tuple[str, list[str]]] = []
    for borough, blocks in borough_groups.items():
        for i in range(0, len(blocks), LEGALS_BATCH_SIZE):
            chunk = blocks[i : i + LEGALS_BATCH_SIZE]
            work_items.append((borough, chunk))

    total_groups = len(work_items)
    completed = 0

    logger.info(
        "ACRIS processing %d block groups across %d boroughs with %d workers",
        total_groups,
        len(borough_groups),
        MAX_WORKERS,
    )

    all_leads: list[Lead] = []
    errors = 0

    # Each thread gets its own Socrata client to avoid sharing connection state
    def _run_group(borough: str, blocks: list[str]) -> list[Lead]:
        client = Socrata("data.cityofnewyork.us", app_token, timeout=45)
        try:
            return _process_block_group(
                client=client,
                borough=borough,
                blocks=blocks,
                bbl_zip_lookup=bbl_zip_lookup,
                bbl_address_lookup=bbl_address_lookup,
                bbl_value_lookup=bbl_value_lookup,
                bbl_units_lookup=bbl_units_lookup,
                min_sale_value=min_sale_value,
                limit_per_block=limit_per_block,
            )
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_run_group, borough, blocks): (borough, blocks)
            for borough, blocks in work_items
        }

        for future in as_completed(futures):
            borough, blocks = futures[future]
            completed += 1

            try:
                group_leads = future.result()
                all_leads.extend(group_leads)
            except Exception as exc:
                errors += 1
                logger.error(
                    "ACRIS group failed for borough=%s blocks=%s: %s",
                    borough,
                    blocks,
                    exc,
                )

            if progress_callback:
                try:
                    progress_callback(completed, total_groups)
                except Exception:
                    pass  # Don't let UI errors break the pipeline

    logger.info(
        "ACRIS scan complete | leads_found=%d | errors=%d",
        len(all_leads),
        errors,
    )

    return all_leads
