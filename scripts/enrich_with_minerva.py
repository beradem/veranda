"""Add phone / email / LinkedIn from Minerva to the LLC & trust owner table.

Reads output/llc_owners.csv, sends the top resolved owners (highest total
value first) to Minerva with their name + home address, and writes the
contact details back into the same CSV. Results are cached, so re-running
never pays for the same person twice.

Usage:
    python3 scripts/enrich_with_minerva.py --usage            # free: show allowance
    python3 scripts/enrich_with_minerva.py --limit 5 --dry-run  # show who would be sent
    python3 scripts/enrich_with_minerva.py --limit 5            # paid test batch
    python3 scripts/enrich_with_minerva.py --limit 10 --entity-type Trust
    python3 scripts/enrich_with_minerva.py --retry-mailing      # re-try misses at mailing address
"""

import argparse
import csv
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.engines.llc_resolver import person_key
from src.engines.minerva_enrichment import (
    ENRICHED_COLUMNS,
    apply_cached_enrichment,
    build_enrich_record,
    build_mailing_address_record,
    check_billing_usage,
    enrich_people,
    load_cache,
    record_id_for,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNERS_CSV = os.path.join(PROJECT_ROOT, "output", "llc_owners.csv")
CACHE_PATH = os.path.join(PROJECT_ROOT, "output", "minerva_cache.json")


def select_targets(
    rows: list[dict], limit: int, entity_type: Optional[str] = None, by_value: bool = False
) -> list[dict]:
    """Pick resolved owners to enrich: one row per person, no managers.

    Default order puts high-confidence identities first (so small test batches
    never pay to look up a wrong person); `by_value` ranks purely by the
    person's total property value.
    """
    confidence_rank = {"High": 0, "Medium": 1}
    eligible = [
        r for r in rows
        if r["owner_full_name"] and r["owner_type"] != "Likely manager / agent"
        and (entity_type is None or r["entity_type"] == entity_type)
    ]
    if by_value:
        eligible.sort(key=lambda r: -float(r["person_total_value"] or 0))
    else:
        eligible.sort(key=lambda r: (confidence_rank.get(r["confidence"], 2), -float(r["person_total_value"] or 0)))
    seen: set[str] = set()
    targets = []
    for row in eligible:
        key = person_key(row["owner_full_name"])
        if key in seen:
            continue
        seen.add(key)
        targets.append(row)
        if len(targets) >= limit:
            break
    return targets


def mailing_address_retries(rows: list[dict], cache: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Build a second lookup for already-tried people who didn't match at home.

    Only people with a mailing address on file that differs from the home.
    """
    targets, records, seen = [], [], set()
    for row in rows:
        if not row.get("owner_full_name") or not row.get("owner_mailing_address"):
            continue
        first_try = cache.get(record_id_for(row))
        if first_try is None or first_try.get("minerva_match"):
            continue
        record_id = record_id_for(row) + "|mail"
        street = row["home_address"].rsplit(",", 1)[0].strip().upper()
        if record_id in seen or row["owner_mailing_address"].upper().startswith(street):
            continue
        seen.add(record_id)
        targets.append(row)
        records.append(build_mailing_address_record(record_id, row["owner_full_name"], row["owner_mailing_address"]))
    return targets, records


def main() -> None:
    """Parse arguments, run enrichment, and write the CSV back."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=5, help="Max people to send (default 5)")
    parser.add_argument("--dry-run", action="store_true", help="List who would be sent; no API call")
    parser.add_argument("--usage", action="store_true", help="Show Minerva allowance (free) and exit")
    parser.add_argument("--by-value", action="store_true", help="Rank purely by total property value")
    parser.add_argument("--entity-type", choices=["LLC", "Trust"], help="Only enrich owners of this entity type")
    parser.add_argument("--retry-mailing", action="store_true",
                        help="Re-try people who didn't match, using their mailing address from city records")
    args = parser.parse_args()

    if args.usage:
        print(check_billing_usage())
        return

    with open(OWNERS_CSV, newline="") as handle:
        rows = list(csv.DictReader(handle))

    if args.retry_mailing:
        targets, records = mailing_address_retries(rows, load_cache(CACHE_PATH))
    else:
        targets = select_targets(rows, args.limit, args.entity_type, args.by_value)
        records = []
        for row in targets:
            street, zip_code = [part.strip() for part in row["home_address"].rsplit(",", 1)]
            records.append(build_enrich_record(record_id_for(row), row["owner_full_name"], street, zip_code))

    if args.dry_run:
        cache = load_cache(CACHE_PATH)
        new = [r for r in records if r["record_id"] not in cache]
        for record in records:
            flag = "cached" if record["record_id"] in cache else "NEW"
            address = record.get("full_address") or f"{record['address_line_1']}, {record['zipcode']}"
            print(f"[{flag}] {record['full_name']} — {address}")
        print(f"\n{len(new)} new record(s) would be sent to Minerva.")
        return

    enrich_people(records, CACHE_PATH)
    updated = apply_cached_enrichment(rows, load_cache(CACHE_PATH))

    fieldnames = list(dict.fromkeys(list(rows[0].keys()) + ENRICHED_COLUMNS))
    with open(OWNERS_CSV, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    cache = load_cache(CACHE_PATH)
    matched = [r for r in records if cache.get(r["record_id"], {}).get("minerva_match")]
    logger.info("Sent %d people; %d matched. Updated %d rows in %s",
                len(targets), len(matched), updated, OWNERS_CSV)


if __name__ == "__main__":
    main()
