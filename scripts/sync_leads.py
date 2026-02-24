"""Quarterly lead sync — runs all Veranda engines at max coverage and saves to SQLite.

This script is meant to run on a schedule (e.g., every 12 weeks via cron) to
keep the database fresh with the latest leads from all sources. Once the DB is
populated, the Streamlit dashboard can serve instant results without live API calls.

Usage:
    python scripts/sync_leads.py

Cron example (every 12 weeks, Sunday 3am):
    0 3 * */3 0 cd /Users/Demirbilek/veranda && python scripts/sync_leads.py >> data/sync.log 2>&1
"""

import logging
import sys
import os

# Add project root to path so imports work when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import get_connection, init_db, save_leads, start_sync_log, complete_sync_log
from src.engines.real_estate import fetch_properties, NEIGHBORHOOD_ZIP_CODES
from src.engines.sec_edgar import fetch_insider_sales, configure_edgar
from src.engines.fec import fetch_fec_donors
from src.models.lead import Lead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def sync_all() -> int:
    """Run all engines at max coverage and save results to the database.

    Returns:
        Total number of leads saved (inserted or updated).
    """
    conn = get_connection()
    init_db(conn)

    sync_id = start_sync_log(conn, source="all")
    total_saved = 0
    all_leads: list[Lead] = []

    try:
        # --- Real Estate: all 50 neighborhoods, no filters ---
        logger.info("Starting Real Estate sync — all %d neighborhoods", len(NEIGHBORHOOD_ZIP_CODES))
        all_zips: list[str] = []
        for zips in NEIGHBORHOOD_ZIP_CODES.values():
            all_zips.extend(zips)
        # Remove duplicates while preserving order
        seen_zips: set[str] = set()
        unique_zips: list[str] = []
        for z in all_zips:
            if z not in seen_zips:
                seen_zips.add(z)
                unique_zips.append(z)

        try:
            re_leads = fetch_properties(
                zip_codes=unique_zips,
                min_market_value=0,
                limit=50_000,
                residential_only=False,
                individuals_only=False,
                include_condos=True,
            )
            logger.info("Real Estate returned %d leads", len(re_leads))
            all_leads.extend(re_leads)
        except Exception as exc:
            logger.error("Real Estate sync failed: %s", exc)

        # --- SEC EDGAR: 90-day lookback, up to 5,000 filings ---
        logger.info("Starting SEC EDGAR sync")
        try:
            configure_edgar()
            sec_leads = fetch_insider_sales(
                lookback_days=90,
                max_filings=5_000,
            )
            logger.info("SEC EDGAR returned %d leads", len(sec_leads))
            all_leads.extend(sec_leads)
        except Exception as exc:
            logger.error("SEC EDGAR sync failed: %s", exc)

        # --- FEC: 365-day lookback, $2,500+ donors, no cap ---
        logger.info("Starting FEC sync")
        try:
            fec_leads = fetch_fec_donors(
                min_donation=2_500.0,
                lookback_days=365,
                max_results=0,
            )
            logger.info("FEC returned %d leads", len(fec_leads))
            all_leads.extend(fec_leads)
        except Exception as exc:
            logger.error("FEC sync failed: %s", exc)

        # --- Save everything to the database ---
        logger.info("Saving %d total leads to database", len(all_leads))
        total_saved = save_leads(conn, all_leads)

        complete_sync_log(conn, sync_id, records_synced=total_saved)
        logger.info(
            "Sync complete: %d leads saved (%d total collected)",
            total_saved,
            len(all_leads),
        )

    except Exception as exc:
        logger.error("Sync failed: %s", exc)
        complete_sync_log(
            conn, sync_id, records_synced=total_saved,
            status="failed", error_message=str(exc),
        )
        raise
    finally:
        conn.close()

    return total_saved


if __name__ == "__main__":
    sync_all()
