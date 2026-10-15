"""LLC Resolver Engine — find the real people behind LLC- and trust-owned homes.

Many wealthy NYC homeowners hold their townhouse in an LLC or a trust for
privacy, so PLUTO only shows us "142 EAST 71 LLC". This engine looks the
property up in other free NYC Open Data records where the city requires a
*named human* to sign on behalf of that owner:

1. HPD Registrations     — buildings must register a Head Officer / owner.
2. DOB NOW permits       — the owner's representative signs every permit.
3. DOB legacy permits    — same idea, for permits filed before DOB NOW.

A person only counts if the record names the *same LLC* — otherwise we could
pick up the previous owner of the house. Trusts are easier: most are named
after the person (see trust_names.py), and a permit filed by someone with the
same surname confirms it. Each entity's citywide portfolio value is also
summed from PLUTO, so we can see owners who hold several properties.

Phone numbers and emails are NOT in these public records (NYC redacts owner
phones), so those columns are left for a paid enrichment step.
"""

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Optional
from urllib.parse import quote_plus

from sodapy import Socrata

from src.engines.trust_names import parse_trust_name
from src.engines.real_estate import (
    PLUTO_RESOURCE_ID,
    SOCRATA_DOMAIN,
    _estimate_market_value,
)

logger = logging.getLogger(__name__)

# --- NYC Open Data resource IDs ---
HPD_REGISTRATIONS_ID = "tesw-yqqr"
HPD_CONTACTS_ID = "feu5-w2e2"
DOB_NOW_PERMITS_ID = "rbx6-tga4"
DOB_LEGACY_PERMITS_ID = "ipu4-2q9a"

# HPD contact types that represent the actual owner (not managing agents)
HPD_OWNER_CONTACT_TYPES = {
    "HeadOfficer", "IndividualOwner", "JointOwner", "Officer", "Shareholder",
}

BOROUGH_CODE_TO_NAME = {
    "1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS", "5": "STATEN ISLAND",
}

# PLUTO owner-name filters for each kind of entity we can resolve
ENTITY_FILTERS = {
    "LLC": "(upper(ownername) like '%LLC%' OR upper(ownername) like '%L.L.C%')",
    "Trust": (
        "upper(ownername) like '%TRUST%' AND upper(ownername) not like '%LLC%' "
        "AND upper(ownername) not like '%L.L.C%'"
    ),
}

# Minimum similarity between two LLC names to treat them as the same entity
LLC_NAME_MATCH_THRESHOLD = 0.85

# Placeholder values that show up in name fields instead of real names
_PLACEHOLDER_NAMES = {"", "N/A", "NA", "NONE", "UNKNOWN", "OWNER", "PR", "TBD"}

LOCATION_BATCH_SIZE = 40
NAME_BATCH_SIZE = 40
MAX_WORKERS = 4

# A person on this many LLCs is probably a manager/agent rather than the owner
MANAGER_LLC_THRESHOLD = 6


@dataclass
class OwnerCandidate:
    """A named person found acting on behalf of an LLC/trust in a public record."""

    full_name: str
    source: str
    on_behalf_of: str = ""
    role: Optional[str] = None
    mailing_address: Optional[str] = None
    record_date: Optional[str] = None


@dataclass
class ResolvedEntity:
    """An LLC or trust plus everything we learned about the people behind it."""

    entity_name: str
    entity_type: str
    properties: list[dict] = field(default_factory=list)
    candidates: list[OwnerCandidate] = field(default_factory=list)


# =========================================================================
# Name helpers
# =========================================================================


def normalize_llc_name(name: str) -> str:
    """Reduce an LLC name to its core words so spelling variants match.

    "High Castle Realty, L.L.C." and "HIGH CASTLE REALTY LLC" both become
    "HIGH CASTLE REALTY".
    """
    cleaned = re.sub(r",?\s*\b(DATED|DTD)\b.*$", "", name.upper())  # trust dates
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", cleaned.replace("L.L.C", "LLC"))
    cleaned = re.sub(r"\b(LLC|L L C|THE|INC|CORP)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def llc_names_match(name_a: Optional[str], name_b: Optional[str]) -> bool:
    """Return True if two LLC names very likely refer to the same entity."""
    if not name_a or not name_b:
        return False
    core_a, core_b = normalize_llc_name(name_a), normalize_llc_name(name_b)
    if not core_a or not core_b:
        return False
    if core_a == core_b:
        return True
    # LLCs are often named after the address — "37 X LLC" and "41 X LLC" differ
    if re.findall(r"\d+", core_a) != re.findall(r"\d+", core_b):
        return False
    return SequenceMatcher(None, core_a, core_b).ratio() >= LLC_NAME_MATCH_THRESHOLD


def clean_person_name(*parts: Optional[str]) -> Optional[str]:
    """Join name parts into a title-cased full name, or None if it's junk.

    Rejects placeholders ("N/A") and names that are actually companies.
    """
    raw = " ".join(p.strip() for p in parts if p and p.strip())
    raw = re.sub(r"\s+", " ", raw).strip(" ,.")
    if raw.upper() in _PLACEHOLDER_NAMES or len(raw.split()) < 2:
        return None
    if re.search(r"\b(LLC|INC|CORP|MGMT|MANAGEMENT|REALTY|TRUST|ASSOC)\b", raw.upper()):
        return None
    return raw.title()


def person_key(full_name: str) -> str:
    """Key for de-duplicating people: first + last token, ignoring middle initials."""
    tokens = re.sub(r"[^A-Z ]", "", full_name.upper()).split()
    return f"{tokens[0]} {tokens[-1]}" if tokens else ""


def _join_address(*parts: Optional[str]) -> Optional[str]:
    """Join address pieces, skipping blanks."""
    text = ", ".join(p.strip() for p in parts if p and p.strip())
    return text or None


def _bbl_parts(bbl: str) -> tuple[str, str, str]:
    """Split a PLUTO BBL like '1000970044.00000000' into (boro, block, lot)."""
    digits = bbl.split(".")[0]
    return digits[0], str(int(digits[1:6])), str(int(digits[6:10]))


def _chunks(items: list, size: int) -> list[list]:
    """Split a list into consecutive chunks of at most `size` items."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def _quote(value: str) -> str:
    """Escape a value for a SoQL string literal."""
    return "'" + value.replace("'", "''") + "'"


# =========================================================================
# Data fetching
# =========================================================================


def fetch_entity_properties(
    client: Socrata,
    zip_codes: list[str],
    entity_type: str,
    min_market_value: float = 1_000_000.0,
) -> list[dict]:
    """Pull 1-2 family homes in the given zips owned by an LLC or a trust."""
    zip_list = ",".join(_quote(z) for z in sorted(set(zip_codes)))
    where = (
        f"zipcode in ({zip_list}) AND assesstot > 0 "
        "AND (bldgclass like 'A%' OR bldgclass like 'B%') "
        f"AND {ENTITY_FILTERS[entity_type]}"
    )
    records: list[dict] = []
    offset = 0
    while True:
        page = client.get(
            PLUTO_RESOURCE_ID, where=where, limit=50000, offset=offset, order="bbl",
            select="bbl,ownername,address,zipcode,assesstot,bldgclass,yearbuilt,bldgarea",
        )
        records.extend(page)
        if len(page) < 50000:
            break
        offset += 50000

    properties = []
    for record in records:
        value = _estimate_market_value(float(record["assesstot"]), record["bldgclass"])
        if value >= min_market_value:
            properties.append({**record, "market_value": value})
    logger.info("PLUTO: %d %s-owned homes >= $%s", len(properties), entity_type, f"{min_market_value:,.0f}")
    return properties


def _fetch_hpd_candidates(client: Socrata, bbls: list[str]) -> dict[str, list[OwnerCandidate]]:
    """Find HPD-registered owners for each BBL whose corporate owner is the LLC."""
    registration_to_bbl: dict[str, str] = {}
    for batch in _chunks(bbls, LOCATION_BATCH_SIZE):
        clauses = []
        for bbl in batch:
            boro, block, lot = _bbl_parts(bbl)
            clauses.append(f"(boroid='{boro}' AND block='{block}' AND lot='{lot}')")
        for row in client.get(HPD_REGISTRATIONS_ID, where=" OR ".join(clauses), limit=5000,
                              select="registrationid,boroid,block,lot"):
            key = f"{row['boroid']}{int(row['block']):05d}{int(row['lot']):04d}"
            registration_to_bbl[row["registrationid"]] = key

    contacts_by_registration: dict[str, list[dict]] = defaultdict(list)
    for batch in _chunks(list(registration_to_bbl), 100):
        ids = ",".join(_quote(r) for r in batch)
        for row in client.get(HPD_CONTACTS_ID, where=f"registrationid in ({ids})", limit=10000):
            contacts_by_registration[row["registrationid"]].append(row)

    results: dict[str, list[OwnerCandidate]] = defaultdict(list)
    for registration_id, contacts in contacts_by_registration.items():
        corporate_names = [c.get("corporationname") for c in contacts if c.get("type") == "CorporateOwner"]
        for contact in contacts:
            if contact.get("type") not in HPD_OWNER_CONTACT_TYPES:
                continue
            name = clean_person_name(contact.get("firstname"), contact.get("lastname"))
            if not name:
                continue
            results[registration_to_bbl[registration_id]].append(OwnerCandidate(
                full_name=name,
                source="HPD registration",
                on_behalf_of="|".join(filter(None, corporate_names)),
                role=contact.get("title") or contact.get("type"),
                mailing_address=_join_address(
                    " ".join(filter(None, [contact.get("businesshousenumber"), contact.get("businessstreetname")])),
                    contact.get("businessapartment"), contact.get("businesscity"),
                    contact.get("businessstate"), contact.get("businesszip"),
                ),
            ))
    return results


def _fetch_dob_now_candidates(client: Socrata, bbls: list[str]) -> dict[str, list[OwnerCandidate]]:
    """Find owners named on DOB NOW permits for each BBL."""
    results: dict[str, list[OwnerCandidate]] = defaultdict(list)
    for batch in _chunks([b.split(".")[0] for b in bbls], LOCATION_BATCH_SIZE * 2):
        ids = ",".join(_quote(b) for b in batch)
        rows = client.get(
            DOB_NOW_PERMITS_ID, where=f"bbl in ({ids})", limit=20000,
            select="bbl,owner_name,owner_business_name,owner_street_address,owner_city,"
                   "owner_state,owner_zip_code,issued_date",
        )
        for row in rows:
            name = clean_person_name(row.get("owner_name"))
            if not name:
                continue
            results[row["bbl"]].append(OwnerCandidate(
                full_name=name,
                source="DOB NOW permit",
                on_behalf_of=row.get("owner_business_name") or "",
                mailing_address=_join_address(
                    row.get("owner_street_address"), row.get("owner_city"),
                    row.get("owner_state"), row.get("owner_zip_code"),
                ),
                record_date=(row.get("issued_date") or "")[:10],
            ))
    return results


def _fetch_dob_legacy_candidates(client: Socrata, bbls: list[str]) -> dict[str, list[OwnerCandidate]]:
    """Find owners named on legacy (pre-DOB NOW) permits for each BBL."""
    results: dict[str, list[OwnerCandidate]] = defaultdict(list)
    for batch in _chunks(bbls, LOCATION_BATCH_SIZE):
        clauses = []
        for bbl in batch:
            boro, block, lot = _bbl_parts(bbl)
            clauses.append(
                f"(borough='{BOROUGH_CODE_TO_NAME[boro]}' AND block='{int(block):05d}' AND lot='{int(lot):05d}')"
            )
        rows = client.get(
            DOB_LEGACY_PERMITS_ID, where=" OR ".join(clauses), limit=20000,
            select="borough,block,lot,owner_s_first_name,owner_s_last_name,owner_s_business_name,"
                   "owner_s_house__,owner_s_house_street_name,city,state,owner_s_zip_code,issuance_date",
        )
        name_to_code = {v: k for k, v in BOROUGH_CODE_TO_NAME.items()}
        for row in rows:
            name = clean_person_name(row.get("owner_s_first_name"), row.get("owner_s_last_name"))
            if not name:
                continue
            key = f"{name_to_code[row['borough']]}{int(row['block']):05d}{int(row['lot']):04d}"
            issued = row.get("issuance_date") or ""
            # Legacy dates are MM/DD/YYYY — store as ISO for sorting
            if re.match(r"\d{2}/\d{2}/\d{4}", issued):
                issued = f"{issued[6:10]}-{issued[0:2]}-{issued[3:5]}"
            results[key].append(OwnerCandidate(
                full_name=name,
                source="DOB permit (legacy)",
                on_behalf_of=row.get("owner_s_business_name") or "",
                mailing_address=_join_address(
                    " ".join(filter(None, [row.get("owner_s_house__"), row.get("owner_s_house_street_name")])),
                    row.get("city"), row.get("state"), row.get("owner_s_zip_code"),
                ),
                record_date=issued[:10],
            ))
    return results


def _fetch_portfolios(client: Socrata, entity_names: list[str]) -> dict[str, tuple[int, float]]:
    """Count every NYC property (any type) held by each entity and sum its value."""
    portfolios: dict[str, tuple[int, float]] = {}
    for batch in _chunks(entity_names, NAME_BATCH_SIZE):
        names = ",".join(_quote(n) for n in batch)
        rows = client.get(PLUTO_RESOURCE_ID, where=f"ownername in ({names}) AND assesstot > 0",
                          select="ownername,assesstot,bldgclass", limit=20000)
        for row in rows:
            count, total = portfolios.get(row["ownername"], (0, 0.0))
            value = _estimate_market_value(float(row["assesstot"]), row.get("bldgclass") or "")
            portfolios[row["ownername"]] = (count + 1, total + value)
    return portfolios


def _run_batched(
    fetcher: Callable[[Socrata, list[str]], dict], client: Socrata, items: list[str], label: str
) -> dict:
    """Run a fetcher over item chunks in parallel and merge the results."""
    chunk_size = max(1, len(items) // (MAX_WORKERS * 4) + 1)
    merged: dict = defaultdict(list) if label != "portfolio" else {}

    def run(chunk: list[str]) -> dict:
        try:
            return fetcher(client, chunk)
        except Exception as exc:  # noqa: BLE001 — one bad batch shouldn't sink the run
            logger.error("%s batch failed (%d items): %s", label, len(chunk), exc)
            return {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for partial in pool.map(run, _chunks(items, chunk_size)):
            for key, value in partial.items():
                if isinstance(merged, defaultdict):
                    merged[key].extend(value)
                else:
                    merged[key] = value
    logger.info("%s: matched %d of %d", label, len(merged), len(items))
    return merged


# =========================================================================
# Resolution
# =========================================================================


def _candidate_belongs_to_entity(
    candidate: OwnerCandidate, entity_name: str, family_surname: Optional[str] = None
) -> bool:
    """Check the record was filed on behalf of this entity (not a prior owner).

    For trusts we also accept a permit filed by someone sharing the trust's
    family surname — e.g. Jane Toth filing for the "TOTH FAMILY TRUST" house.
    """
    if any(llc_names_match(name, entity_name) for name in candidate.on_behalf_of.split("|")):
        return True
    if family_surname:
        return person_key(candidate.full_name).split(" ")[-1] == person_key(family_surname).split(" ")[-1]
    return False


def pick_best_owner(candidates: list[OwnerCandidate]) -> Optional[dict]:
    """Choose the most likely real owner among verified candidates.

    The person a trust is named after always wins (relatives who filed
    permits are listed as other people). Otherwise, people confirmed by more
    independent sources win, and ties go to the most recent record.
    """
    if not candidates:
        return None
    grouped: dict[str, list[OwnerCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[person_key(candidate.full_name)].append(candidate)

    def score(group: list[OwnerCandidate]) -> tuple[bool, int, str]:
        sources = {c.source for c in group}
        latest = max((c.record_date or "" for c in group if c.source != "HPD registration"), default="")
        # HPD registrations are current by definition — treat as most recent
        if "HPD registration" in sources:
            latest = "9999"
        return "Trust name" in sources, len(sources), latest

    best = max(grouped.values(), key=score)
    sources = sorted({c.source for c in best})
    addresses = [c.mailing_address for c in best if c.mailing_address]
    roles = [c.role for c in best if c.role]
    others = sorted({g[0].full_name for k, g in grouped.items() if g is not best})
    return {
        "full_name": max((c.full_name for c in best), key=len),
        "sources": sources,
        "role": roles[0] if roles else None,
        "mailing_address": addresses[0] if addresses else None,
        "other_people": others,
        "confidence": "High" if len(sources) >= 2 else "Medium",
    }


def linkedin_search_url(full_name: str) -> str:
    """Build a LinkedIn people-search link (not a verified profile)."""
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(full_name + ' New York')}"


def _trust_name_candidate(entity_name: str) -> tuple[Optional[OwnerCandidate], Optional[str]]:
    """Read the person straight out of a trust's name.

    Returns:
        (candidate if a full name was found, family surname if any)
    """
    parsed = parse_trust_name(entity_name)
    candidate = None
    if parsed.full_name:
        candidate = OwnerCandidate(full_name=parsed.full_name, source="Trust name", on_behalf_of=entity_name)
    return candidate, parsed.surname


def resolve_hidden_owners(
    zip_codes: list[str],
    entity_types: tuple[str, ...] = ("LLC", "Trust"),
    min_market_value: float = 1_000_000.0,
    app_token: Optional[str] = None,
) -> list[dict]:
    """Run the full pipeline and return one row per LLC/trust, best leads first.

    Args:
        zip_codes: NYC zip codes to scan.
        entity_types: Which kinds of owner entity to resolve (keys of ENTITY_FILTERS).
        min_market_value: Minimum estimated home value to include.
        app_token: Optional Socrata app token for higher rate limits.

    Returns:
        List of row dicts ready for a table / CSV.
    """
    client = Socrata(SOCRATA_DOMAIN, app_token, timeout=180)
    try:
        properties: list[dict] = []
        for entity_type in entity_types:
            for prop in fetch_entity_properties(client, zip_codes, entity_type, min_market_value):
                properties.append({**prop, "entity_type": entity_type})
        bbls = [p["bbl"].split(".")[0] for p in properties]

        hpd = _run_batched(_fetch_hpd_candidates, client, bbls, "HPD")
        dob_now = _run_batched(_fetch_dob_now_candidates, client, bbls, "DOB NOW")
        dob_legacy = _run_batched(_fetch_dob_legacy_candidates, client, bbls, "DOB legacy")

        entities: dict[str, ResolvedEntity] = {}
        for prop in properties:
            bbl = prop["bbl"].split(".")[0]
            entry = entities.setdefault(
                prop["ownername"], ResolvedEntity(entity_name=prop["ownername"], entity_type=prop["entity_type"])
            )
            entry.properties.append(prop)
            surname = None
            if entry.entity_type == "Trust":
                name_candidate, surname = _trust_name_candidate(entry.entity_name)
                if name_candidate and not entry.candidates:
                    entry.candidates.append(name_candidate)
            for candidate in hpd.get(bbl, []) + dob_now.get(bbl, []) + dob_legacy.get(bbl, []):
                if _candidate_belongs_to_entity(candidate, entry.entity_name, surname):
                    entry.candidates.append(candidate)

        portfolios = _run_batched(_fetch_portfolios, client, list(entities), "portfolio")
    finally:
        client.close()

    rows = []
    for entry in entities.values():
        count, value = portfolios.get(entry.entity_name, (0, 0.0))
        target_value = sum(p["market_value"] for p in entry.properties)
        best = pick_best_owner(entry.candidates)
        first_property = max(entry.properties, key=lambda p: p["market_value"])
        rows.append({
            "owner_full_name": best["full_name"] if best else None,
            "owner_role": best["role"] if best else None,
            "confidence": best["confidence"] if best else "Unresolved",
            "evidence": ", ".join(best["sources"]) if best else None,
            "entity_type": entry.entity_type,
            "entity_name": entry.entity_name,
            "entity_portfolio_properties": max(count, len(entry.properties)),
            "entity_portfolio_value": round(max(value, target_value)),
            "home_address": f"{first_property['address']}, {first_property['zipcode']}",
            "home_value": round(first_property["market_value"]),
            "owner_mailing_address": best["mailing_address"] if best else None,
            "phone": None,
            "email": None,
            "linkedin_search": linkedin_search_url(best["full_name"]) if best else None,
            "other_people_named": "; ".join(best["other_people"]) if best else None,
        })
    return _add_person_portfolios(rows)


def classify_owner(person_entity_count: int, entity_property_count: int) -> str:
    """Label who we're likely dealing with, so outreach can be tailored.

    Someone named on many unrelated LLCs is usually a property manager or
    family-office employee, not the owner — still a door in, but not the client.
    """
    if person_entity_count >= MANAGER_LLC_THRESHOLD:
        return "Likely manager / agent"
    if person_entity_count >= 2 or entity_property_count >= 4:
        return "Investor"
    return "Private homeowner"


def _add_person_portfolios(rows: list[dict]) -> list[dict]:
    """Total each person's holdings across every LLC/trust they control, then sort."""
    by_person: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["owner_full_name"]:
            by_person[person_key(row["owner_full_name"])].append(row)
    for row in rows:
        group = by_person.get(person_key(row["owner_full_name"] or ""), [row]) if row["owner_full_name"] else [row]
        row["person_entity_count"] = len(group)
        row["person_total_value"] = sum(r["entity_portfolio_value"] for r in group)
        row["owner_type"] = classify_owner(row["person_entity_count"], row["entity_portfolio_properties"])

    confidence_rank = {"High": 0, "Medium": 1, "Unresolved": 2}
    rows.sort(key=lambda r: (confidence_rank[r["confidence"]], -r["person_total_value"]))
    return rows
