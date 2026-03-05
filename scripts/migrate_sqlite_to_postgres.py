"""One-time migration: copy leads (and optionally sync_log) from SQLite to PostgreSQL.

Use this after you create a Supabase project and have DATABASE_URL in .env.
It reads from data/veranda.db and writes to the PostgreSQL database.

Usage:
    # Ensure .env has DATABASE_URL=postgresql://... (from Supabase dashboard)
    python scripts/migrate_sqlite_to_postgres.py

The script creates the PostgreSQL tables if they don't exist, then copies all
rows from the SQLite leads table. Sync log entries are copied too so you keep
your last sync timestamp. Existing rows in PostgreSQL are not cleared; run
clear_leads from the app or manually TRUNCATE leads if you want a clean slate.
"""

import logging
import os
import sqlite3
import sys

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Lead columns in order (same in SQLite and PostgreSQL schema); we omit id for INSERT
LEAD_COLUMNS = [
    "first_name", "last_name", "name_key", "city", "state", "zip_code", "address",
    "professional_title", "company", "linkedin_url", "email", "phone",
    "email_reveal_attempted", "phone_reveal_attempted", "estimated_wealth",
    "discovery_trigger", "year_built", "num_floors", "building_area", "lot_area",
    "building_type", "unit_number", "deed_sale_amount", "deed_date",
    "source", "confidence_score", "discovered_at", "outreach_status", "outreach_draft",
    "created_at", "updated_at",
]

SYNC_LOG_COLUMNS = ["started_at", "completed_at", "records_synced", "source", "status", "error_message"]


def main() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or not url.startswith("postgresql"):
        logger.error("DATABASE_URL must be set and start with postgresql (e.g. from Supabase).")
        sys.exit(1)

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "veranda.db",
    )
    if not os.path.isfile(db_path):
        logger.error("SQLite database not found at %s", db_path)
        sys.exit(1)

    import psycopg2
    import psycopg2.extras

    sqlite_conn = sqlite3.connect(db_path)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = psycopg2.connect(url)
    pg_conn.autocommit = False

    try:
        # Ensure PostgreSQL schema exists
        from src.db import SCHEMA_PG_SQL
        cur = pg_conn.cursor()
        for stmt in SCHEMA_PG_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cur.close()
        pg_conn.commit()
        logger.info("PostgreSQL schema ensured.")

        # Copy leads
        rows = sqlite_conn.execute(
            f"SELECT {', '.join(LEAD_COLUMNS)} FROM leads"
        ).fetchall()
        if not rows:
            logger.info("No leads in SQLite to migrate.")
        else:
            cols = ", ".join(LEAD_COLUMNS)
            insert = f"INSERT INTO leads ({cols}) VALUES %s"
            data = [[row[c] for c in LEAD_COLUMNS] for row in rows]
            BATCH = 1000
            cur = pg_conn.cursor()
            for i in range(0, len(data), BATCH):
                psycopg2.extras.execute_values(cur, insert, data[i:i + BATCH])
                pg_conn.commit()
                logger.info("  ...inserted %d / %d leads", min(i + BATCH, len(data)), len(data))
            cur.close()
            logger.info("Migrated %d leads to PostgreSQL.", len(rows))

        # Copy sync_log (optional; preserves last sync time)
        sync_rows = sqlite_conn.execute(
            f"SELECT {', '.join(SYNC_LOG_COLUMNS)} FROM sync_log ORDER BY id"
        ).fetchall()
        if sync_rows:
            placeholders = ", ".join("%s" for _ in SYNC_LOG_COLUMNS)
            insert = f"INSERT INTO sync_log ({', '.join(SYNC_LOG_COLUMNS)}) VALUES ({placeholders})"
            cur = pg_conn.cursor()
            for row in sync_rows:
                cur.execute(insert, [row[c] for c in SYNC_LOG_COLUMNS])
            pg_conn.commit()
            cur.close()
            logger.info("Migrated %d sync_log rows to PostgreSQL.", len(sync_rows))

    finally:
        sqlite_conn.close()
        pg_conn.close()

    logger.info("Migration complete. You can now set DATABASE_URL in production and run the app.")


if __name__ == "__main__":
    main()
