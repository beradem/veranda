"""Export a table of LLC- and trust-owned luxury homes and the people behind them.

Scans every neighborhood in our preset list, resolves each LLC/trust to a
named person using free NYC Open Data, and writes output/llc_owners.csv.

Usage:
    python3 scripts/resolve_llc_owners.py
"""

import csv
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.engines.llc_resolver import resolve_hidden_owners
from src.engines.minerva_enrichment import ENRICHED_COLUMNS, apply_cached_enrichment, load_cache
from src.engines.real_estate import NEIGHBORHOOD_ZIP_CODES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "llc_owners.csv")
MINERVA_CACHE_PATH = os.path.join(OUTPUT_DIR, "minerva_cache.json")


def main() -> None:
    """Run the resolver and write the CSV."""
    zip_codes = sorted({z for zips in NEIGHBORHOOD_ZIP_CODES.values() for z in zips})
    rows = resolve_hidden_owners(zip_codes, app_token=os.getenv("SOCRATA_APP_TOKEN"))
    # Keep any contact details we already paid Minerva for
    apply_cached_enrichment(rows, load_cache(MINERVA_CACHE_PATH))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="") as handle:
        fieldnames = list(dict.fromkeys(list(rows[0].keys()) + ENRICHED_COLUMNS))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    resolved = sum(1 for r in rows if r["owner_full_name"])
    logger.info("Wrote %d LLCs/trusts (%d resolved to a person) to %s", len(rows), resolved, OUTPUT_PATH)


if __name__ == "__main__":
    main()
