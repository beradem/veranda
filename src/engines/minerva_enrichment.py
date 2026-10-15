"""Minerva enrichment — turn a name + home address into phone, email, LinkedIn.

Minerva (https://docs.minerva.io) matches a person from their name plus a
postal address, then returns their contact details. Think of it as handing a
concierge a name and a street address and getting back a business card.

We use the REST endpoint directly (POST /v2/enrich) because the Python SDK
does not yet accept postal addresses as a lookup key.

Cost control:
  * Billing is per unique record exported, so every result is cached in
    output/minerva_cache.json — the same person is never sent twice.
  * check_billing_usage() is free and shows remaining allowance before a run.
"""

import json
import logging
import os
from typing import Optional

import httpx

from src.engines.llc_resolver import person_key

logger = logging.getLogger(__name__)

MINERVA_BASE_URL = "https://api.minerva.io"
ENRICH_PATH = "/v2/enrich"
BILLING_PATH = "/billing/usage"
MAX_RECORDS_PER_REQUEST = 500

# Columns written onto the owner table
ENRICHED_COLUMNS = [
    "phone", "phone_type", "email", "work_email", "linkedin_url", "linkedin_title",
    "estimated_wealth_range", "estimated_income_range", "minerva_match",
]

RETURN_FIELDS = [
    "full_name",
    "personal_emails",
    "professional_emails",
    "phones",
    "linkedin_url",
    "linkedin_title",
    "estimated_wealth_range",
    "estimated_income_range",
]


def _get_api_key() -> str:
    """Read the Minerva API key from the environment.

    Raises:
        ValueError: If MINERVA_API_KEY is not set.
    """
    key = os.environ.get("MINERVA_API_KEY", "").strip()
    if not key:
        raise ValueError("MINERVA_API_KEY is not set. Add it to your .env file.")
    return key


def check_billing_usage() -> dict:
    """Return Minerva's org billing summary (free — exports no records)."""
    response = httpx.get(
        MINERVA_BASE_URL + BILLING_PATH, headers={"x-api-key": _get_api_key()}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def build_enrich_record(record_id: str, full_name: str, street_address: str, zip_code: str) -> dict:
    """Shape one person into a Minerva 'name + parsed address' lookup."""
    return {
        "record_id": record_id,
        "full_name": full_name,
        "address_line_1": street_address,
        "zipcode": zip_code,
    }


def build_mailing_address_record(record_id: str, full_name: str, mailing_address: str) -> dict:
    """Lookup using the mailing address from city records (often the real home)."""
    return {"record_id": record_id, "full_name": full_name, "full_address": mailing_address}


def _first(items: Optional[list], key: str) -> Optional[str]:
    """Return `key` from the top-ranked item of a Minerva ranked list."""
    if not items:
        return None
    rank_key = next((k for k in items[0] if k.endswith("_rank")), None)
    ranked = sorted(items, key=lambda item: item.get(rank_key) or 99) if rank_key else items
    return ranked[0].get(key)


def summarize_result(result: dict) -> dict:
    """Flatten a Minerva result into the columns our lead table uses."""
    if not result.get("is_match"):
        return {"minerva_match": False}
    phones = result.get("phones") or []
    mobile = [p for p in phones if (p.get("phone_type") or "").lower() == "mobile"]
    return {
        "minerva_match": True,
        "minerva_pid": result.get("minerva_pid"),
        "minerva_match_score": result.get("match_score"),
        "phone": _first(mobile or phones, "phone_number"),
        "phone_type": _first(mobile or phones, "phone_type"),
        "email": _first(result.get("personal_emails"), "email_address")
        or _first(result.get("professional_emails"), "email_address"),
        "work_email": _first(result.get("professional_emails"), "email_address"),
        "linkedin_url": result.get("linkedin_url"),
        "linkedin_title": result.get("linkedin_title"),
        "estimated_wealth_range": result.get("estimated_wealth_range"),
        "estimated_income_range": result.get("estimated_income_range"),
    }


def load_cache(cache_path: str) -> dict[str, dict]:
    """Load previously paid-for results, keyed by record_id."""
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path) as handle:
        return json.load(handle)


def _save_cache(cache_path: str, cache: dict[str, dict]) -> None:
    """Write the cache to disk after every batch so a crash never loses paid data."""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as handle:
        json.dump(cache, handle, indent=1)


def enrich_people(records: list[dict], cache_path: str) -> dict[str, dict]:
    """Enrich records via Minerva, skipping anyone already in the cache.

    Args:
        records: Output of build_enrich_record().
        cache_path: JSON file holding earlier results.

    Returns:
        Mapping of record_id -> summarized result for every input record.
    """
    cache = load_cache(cache_path)
    pending = [r for r in records if r["record_id"] not in cache]
    logger.info("Minerva: %d records requested, %d already cached, %d to send",
                len(records), len(records) - len(pending), len(pending))

    headers = {"x-api-key": _get_api_key(), "Content-Type": "application/json"}
    with httpx.Client(base_url=MINERVA_BASE_URL, headers=headers, timeout=120) as client:
        for start in range(0, len(pending), MAX_RECORDS_PER_REQUEST):
            batch = pending[start:start + MAX_RECORDS_PER_REQUEST]
            response = client.post(ENRICH_PATH, json={"records": batch, "return_fields": RETURN_FIELDS})
            if response.status_code == 402:
                logger.error("Minerva: out of record allowance — stopping. %s", response.text[:300])
                break
            response.raise_for_status()
            for result in response.json().get("results", []):
                if result.get("validation_errors"):
                    logger.warning("Minerva validation errors for %s: %s",
                                   result.get("record_id"), result["validation_errors"])
                cache[result["record_id"]] = summarize_result(result)
            _save_cache(cache_path, cache)
            logger.info("Minerva: batch done (%d/%d)", min(start + len(batch), len(pending)), len(pending))

    return {r["record_id"]: cache[r["record_id"]] for r in records if r["record_id"] in cache}


def record_id_for(row: dict) -> str:
    """Stable ID per person + home zip, so the cache survives table re-runs."""
    zip_code = row["home_address"].rsplit(",", 1)[-1].strip()
    return f"{person_key(row['owner_full_name'])}|{zip_code}".replace(" ", "_")


def apply_cached_enrichment(rows: list[dict], cache: dict[str, dict]) -> int:
    """Copy cached Minerva results onto every row for that person.

    We look each person up once (at one of their addresses) and share the
    result across all their LLC/trust rows — the same name-based grouping the
    table already uses for person_total_value. If a person was looked up more
    than once (home address, then mailing address), a match wins.

    Returns:
        Number of rows updated.
    """
    by_person: dict[str, dict] = {}
    for record_id, result in cache.items():
        person = record_id.split("|")[0]
        if person not in by_person or (result.get("minerva_match") and not by_person[person].get("minerva_match")):
            by_person[person] = result

    updated = 0
    for row in rows:
        if not row.get("owner_full_name"):
            continue
        result = by_person.get(record_id_for(row).split("|")[0])
        if result is None:
            continue
        for column in ENRICHED_COLUMNS:
            row[column] = result.get(column)
        updated += 1
    return updated
