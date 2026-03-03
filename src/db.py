"""Persistence layer for Veranda leads (SQLite locally, PostgreSQL on Supabase).

Think of this module as a filing cabinet for all the leads Veranda discovers.
Instead of fetching thousands of records from live APIs every time you click
"Generate Leads," we save them here once and query them instantly afterward.

The database stores leads in a single table with deduplication by name — if
the same person appears from multiple sources, we keep the record with the
highest estimated wealth.

When DATABASE_URL is set (e.g. postgresql://... from Supabase), the app uses
PostgreSQL. Otherwise it uses SQLite (data/veranda.db) for local development.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.models.lead import Lead, LeadSource, OutreachStatus

logger = logging.getLogger(__name__)

# When set to "postgresql", get_connection() uses DATABASE_URL and psycopg2.
_engine: Optional[str] = None

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "veranda.db",
)

# SQLite schema (local dev)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name       TEXT NOT NULL,
    last_name        TEXT NOT NULL,
    name_key         TEXT NOT NULL,
    city             TEXT,
    state            TEXT,
    zip_code         TEXT,
    address          TEXT,
    professional_title TEXT,
    company          TEXT,
    linkedin_url     TEXT,
    email            TEXT,
    phone            TEXT,
    email_reveal_attempted  INTEGER NOT NULL DEFAULT 0,
    phone_reveal_attempted  INTEGER NOT NULL DEFAULT 0,
    estimated_wealth REAL,
    discovery_trigger TEXT NOT NULL,
    year_built       INTEGER,
    num_floors       INTEGER,
    building_area    INTEGER,
    lot_area         INTEGER,
    building_type    TEXT,
    unit_number      TEXT,
    deed_sale_amount REAL,
    deed_date        TEXT,
    source           TEXT NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    discovered_at    TEXT NOT NULL,
    outreach_status  TEXT NOT NULL DEFAULT 'pending',
    outreach_draft   TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_leads_name_key ON leads(name_key);
CREATE INDEX IF NOT EXISTS idx_leads_zip_code ON leads(zip_code);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_estimated_wealth ON leads(estimated_wealth);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    records_synced  INTEGER DEFAULT 0,
    source          TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    error_message   TEXT
);
"""

# PostgreSQL schema (Supabase / production)
SCHEMA_PG_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id               SERIAL PRIMARY KEY,
    first_name       TEXT NOT NULL,
    last_name        TEXT NOT NULL,
    name_key         TEXT NOT NULL,
    city             TEXT,
    state            TEXT,
    zip_code         TEXT,
    address          TEXT,
    professional_title TEXT,
    company          TEXT,
    linkedin_url     TEXT,
    email            TEXT,
    phone            TEXT,
    email_reveal_attempted  INTEGER NOT NULL DEFAULT 0,
    phone_reveal_attempted  INTEGER NOT NULL DEFAULT 0,
    estimated_wealth DOUBLE PRECISION,
    discovery_trigger TEXT NOT NULL,
    year_built       INTEGER,
    num_floors       INTEGER,
    building_area    INTEGER,
    lot_area         INTEGER,
    building_type    TEXT,
    unit_number      TEXT,
    deed_sale_amount DOUBLE PRECISION,
    deed_date        TEXT,
    source           TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    discovered_at    TEXT NOT NULL,
    outreach_status  TEXT NOT NULL DEFAULT 'pending',
    outreach_draft   TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leads_name_key ON leads(name_key);
CREATE INDEX IF NOT EXISTS idx_leads_zip_code ON leads(zip_code);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_estimated_wealth ON leads(estimated_wealth);

CREATE TABLE IF NOT EXISTS sync_log (
    id              SERIAL PRIMARY KEY,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    records_synced  INTEGER DEFAULT 0,
    source          TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    error_message   TEXT
);
"""


def _is_postgresql() -> bool:
    """True if the app is configured to use PostgreSQL (DATABASE_URL)."""
    global _engine
    if _engine is not None:
        return _engine == "postgresql"
    url = os.environ.get("DATABASE_URL", "").strip()
    if url and url.startswith("postgresql"):
        _engine = "postgresql"
        return True
    _engine = "sqlite"
    return False


def _placeholder_query(query: str) -> str:
    """Convert %s placeholders to ? for SQLite so one query style works for both."""
    if _engine == "postgresql":
        return query
    return query.replace("%s", "?")


def _cursor(conn: Any):
    """Return a cursor that yields dict-like rows (Row for SQLite, RealDictCursor for PG)."""
    if _engine == "postgresql":
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def get_connection(db_path: str = DEFAULT_DB_PATH) -> Any:
    """Open a database connection (SQLite or PostgreSQL).

    If the environment variable DATABASE_URL is set and starts with "postgresql",
    connects to that database (e.g. Supabase). Otherwise uses SQLite at db_path.
    Passing ":memory:" forces SQLite (for tests) and ignores DATABASE_URL.

    Args:
        db_path: Path to the SQLite file. Used only when not using DATABASE_URL.
                 Defaults to data/veranda.db. Use ":memory:" for tests.

    Returns:
        A connection with .cursor(), .commit(), .rollback(). Cursors return
        dict-like rows (row["column_name"]).
    """
    global _engine
    if db_path == ":memory:":
        _engine = "sqlite"
    else:
        url = os.environ.get("DATABASE_URL", "").strip()
        if url and url.startswith("postgresql"):
            import psycopg2
            _engine = "postgresql"
            conn = psycopg2.connect(url)
            conn.autocommit = False
            return conn
        _engine = "sqlite"
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate_db_sqlite(conn: sqlite3.Connection) -> None:
    """Add any columns that exist in the schema but not in the live table (SQLite only).

    SQLite's CREATE TABLE IF NOT EXISTS won't add new columns to an existing
    table, so this function uses PRAGMA table_info to detect missing columns
    and ALTER TABLE to add them without data loss.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    additions = {
        "phone": "TEXT",
        "email_reveal_attempted": "INTEGER NOT NULL DEFAULT 0",
        "phone_reveal_attempted": "INTEGER NOT NULL DEFAULT 0",
    }
    for col, definition in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {definition}")
    conn.commit()


def init_db(conn: Any) -> None:
    """Create tables and indexes if they don't exist.

    Uses PostgreSQL schema when DATABASE_URL is set, otherwise SQLite.
    Idempotent — safe to call every time the app starts.
    """
    if _engine == "postgresql":
        cur = _cursor(conn)
        try:
            for stmt in SCHEMA_PG_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        finally:
            cur.close()
        conn.commit()
    else:
        conn.executescript(SCHEMA_SQL)
        _migrate_db_sqlite(conn)
    logger.info("Database schema initialized")


def _make_name_key(first_name: str, last_name: str) -> str:
    """Build a dedup key from first and last name."""
    return f"{first_name}_{last_name}".lower().strip("_")


def _safe_get(row: Any, key: str):
    """Return row[key] or None if the column doesn't exist (pre-migration rows)."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _lead_to_row(lead: Lead) -> dict:
    """Convert a Lead model to a dict matching the DB columns."""
    return {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "name_key": _make_name_key(lead.first_name, lead.last_name),
        "city": lead.city,
        "state": lead.state,
        "zip_code": lead.zip_code,
        "address": lead.address,
        "professional_title": lead.professional_title,
        "company": lead.company,
        "linkedin_url": lead.linkedin_url,
        "email": lead.email,
        "phone": lead.phone,
        "email_reveal_attempted": lead.email_reveal_attempted,
        "phone_reveal_attempted": lead.phone_reveal_attempted,
        "estimated_wealth": lead.estimated_wealth,
        "discovery_trigger": lead.discovery_trigger,
        "year_built": lead.year_built,
        "num_floors": lead.num_floors,
        "building_area": lead.building_area,
        "lot_area": lead.lot_area,
        "building_type": lead.building_type,
        "unit_number": lead.unit_number,
        "deed_sale_amount": lead.deed_sale_amount,
        "deed_date": lead.deed_date,
        "source": lead.source.value,
        "confidence_score": lead.confidence_score,
        "discovered_at": lead.discovered_at.isoformat(),
        "outreach_status": lead.outreach_status.value,
        "outreach_draft": lead.outreach_draft,
    }


def _row_to_lead(row: Any) -> Lead:
    """Convert a DB row back into a Lead model."""
    return Lead(
        first_name=row["first_name"],
        last_name=row["last_name"],
        city=row["city"],
        state=row["state"],
        zip_code=row["zip_code"],
        address=row["address"],
        professional_title=row["professional_title"],
        company=row["company"],
        linkedin_url=row["linkedin_url"],
        email=row["email"],
        phone=_safe_get(row, "phone"),
        email_reveal_attempted=_safe_get(row, "email_reveal_attempted") or 0,
        phone_reveal_attempted=_safe_get(row, "phone_reveal_attempted") or 0,
        estimated_wealth=row["estimated_wealth"],
        discovery_trigger=row["discovery_trigger"],
        year_built=row["year_built"],
        num_floors=row["num_floors"],
        building_area=row["building_area"],
        lot_area=row["lot_area"],
        building_type=row["building_type"],
        unit_number=row["unit_number"],
        deed_sale_amount=row["deed_sale_amount"],
        deed_date=row["deed_date"],
        source=LeadSource(row["source"]),
        confidence_score=row["confidence_score"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        outreach_status=OutreachStatus(row["outreach_status"]),
        outreach_draft=row["outreach_draft"],
    )


def _sql_now() -> str:
    """Expression for current timestamp in SQL (backend-specific)."""
    return "CURRENT_TIMESTAMP" if _engine == "postgresql" else "datetime('now')"


def save_leads(conn: Any, leads: list[Lead]) -> int:
    """Save leads to the database with deduplication.

    For each lead, we compute a name_key (lowercase "first_last"). If a row
    with that key already exists, we only update it if the incoming lead has
    a higher estimated_wealth. This keeps the best data per person.

    Args:
        conn: Database connection.
        leads: List of Lead objects to save.

    Returns:
        Number of leads inserted or updated.
    """
    saved = 0
    cur = _cursor(conn)
    now = _sql_now()

    try:
        for lead in leads:
            row = _lead_to_row(lead)
            name_key = row["name_key"]

            q = _placeholder_query("SELECT id, estimated_wealth FROM leads WHERE name_key = %s")
            cur.execute(q, (name_key,))
            existing = cur.fetchone()

            if existing is None:
                columns = ", ".join(row.keys())
                placeholders = ", ".join("%s" for _ in row)
                q = _placeholder_query(
                    f"INSERT INTO leads ({columns}) VALUES ({placeholders})"
                )
                cur.execute(q, list(row.values()))
                saved += 1
            else:
                incoming_wealth = row["estimated_wealth"] or 0
                existing_wealth = existing["estimated_wealth"] or 0
                if incoming_wealth > existing_wealth:
                    keys = [k for k in row.keys() if k != "name_key"]
                    set_clause = ", ".join(f"{k} = %s" for k in keys)
                    q = _placeholder_query(
                        f"UPDATE leads SET {set_clause}, updated_at = {now} WHERE id = %s"
                    )
                    values = [row[k] for k in keys] + [existing["id"]]
                    cur.execute(q, values)
                    saved += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    logger.info("Saved %d leads (of %d total)", saved, len(leads))
    return saved


def query_leads(
    conn: Any,
    zip_codes: Optional[list[str]] = None,
    min_value: float = 0,
    max_value: Optional[float] = None,
    residential_only: bool = False,
    individuals_only: bool = False,
    limit: Optional[int] = None,
) -> list[Lead]:
    """Query leads from the database with optional filters.

    Args:
        conn: Database connection.
        zip_codes: If provided, only return leads in these zip codes.
        min_value: Minimum estimated_wealth threshold.
        max_value: Maximum estimated_wealth threshold (exclusive).
        residential_only: If True, only return tax_assessor leads.
        individuals_only: If True, exclude leads with empty first_name (LLCs).
        limit: Maximum number of rows to return (applied at SQL level).

    Returns:
        List of Lead objects sorted by estimated_wealth descending.
    """
    conditions = []
    params: list = []

    if zip_codes:
        ph = ", ".join("%s" for _ in zip_codes)
        conditions.append(f"zip_code IN ({ph})")
        params.extend(zip_codes)

    if min_value > 0:
        conditions.append("estimated_wealth >= %s")
        params.append(min_value)

    if max_value is not None:
        conditions.append("estimated_wealth < %s")
        params.append(max_value)

    # Exclude any lead whose first or last name contains a digit
    if _engine == "postgresql":
        conditions.append("first_name !~ '[0-9]'")
        conditions.append("last_name !~ '[0-9]'")
    else:
        conditions.append("first_name NOT GLOB '*[0-9]*'")
        conditions.append("last_name NOT GLOB '*[0-9]*'")

    if residential_only:
        conditions.append("source = %s")
        params.append(LeadSource.TAX_ASSESSOR.value)

    if individuals_only:
        conditions.append("first_name != ''")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = f"LIMIT {limit}" if limit else ""
    q = _placeholder_query(
        f"SELECT * FROM leads {where} ORDER BY estimated_wealth DESC {limit_clause}"
    )
    cur = _cursor(conn)
    try:
        cur.execute(q, params)
        rows = cur.fetchall()
    finally:
        cur.close()
    return [_row_to_lead(row) for row in rows]


def get_lead_count(conn: Any) -> int:
    """Return total number of leads in the database."""
    q = _placeholder_query("SELECT COUNT(*) as cnt FROM leads")
    cur = _cursor(conn)
    try:
        cur.execute(q)
        result = cur.fetchone()
        return result["cnt"]
    finally:
        cur.close()


def get_last_sync(conn: Any) -> Optional[str]:
    """Return the timestamp of the most recent completed sync, or None."""
    q = _placeholder_query(
        "SELECT completed_at FROM sync_log "
        "WHERE status = %s ORDER BY completed_at DESC LIMIT 1"
    )
    cur = _cursor(conn)
    try:
        cur.execute(q, ("completed",))
        row = cur.fetchone()
        return row["completed_at"] if row else None
    finally:
        cur.close()


def start_sync_log(conn: Any, source: Optional[str] = None) -> int:
    """Record the start of a sync run.

    Returns:
        The sync log ID for later updates.
    """
    cur = _cursor(conn)
    try:
        if _engine == "postgresql":
            q = _placeholder_query(
                "INSERT INTO sync_log (started_at, source, status) VALUES (%s, %s, 'running') RETURNING id"
            )
            cur.execute(q, (datetime.utcnow().isoformat(), source))
            sync_id = int(cur.fetchone()["id"])
        else:
            q = _placeholder_query(
                "INSERT INTO sync_log (started_at, source, status) VALUES (%s, %s, 'running')"
            )
            cur.execute(q, (datetime.utcnow().isoformat(), source))
            sync_id = cur.lastrowid
        conn.commit()
        return sync_id
    finally:
        cur.close()


def complete_sync_log(
    conn: Any,
    sync_id: int,
    records_synced: int,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> None:
    """Record the end of a sync run."""
    q = _placeholder_query(
        "UPDATE sync_log SET completed_at = %s, records_synced = %s, "
        "status = %s, error_message = %s WHERE id = %s"
    )
    cur = _cursor(conn)
    try:
        cur.execute(
            q,
            (
                datetime.utcnow().isoformat(),
                records_synced,
                status,
                error_message,
                sync_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()


def clear_leads(conn: Any) -> int:
    """Delete all rows from the leads table.

    Use this to force a fresh live pull next time Generate Leads is clicked.

    Returns:
        Number of rows deleted.
    """
    q = _placeholder_query("DELETE FROM leads")
    cur = _cursor(conn)
    try:
        cur.execute(q)
        conn.commit()
        logger.info("Cleared %d leads from database", cur.rowcount)
        return cur.rowcount
    finally:
        cur.close()


def update_outreach(
    conn: Any,
    name_key: str,
    status: str,
    draft: Optional[str] = None,
) -> bool:
    """Persist an outreach draft and status for a lead.

    Args:
        conn: Database connection.
        name_key: The dedup key (lowercase "first_last").
        status: New outreach status value.
        draft: Outreach message text (optional).

    Returns:
        True if a row was updated, False if no matching lead found.
    """
    now = _sql_now()
    q = _placeholder_query(
        f"UPDATE leads SET outreach_status = %s, outreach_draft = %s, updated_at = {now} WHERE name_key = %s"
    )
    cur = _cursor(conn)
    try:
        cur.execute(q, (status, draft, name_key))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()


def reveal_contact(
    conn: Any,
    name_key: str,
    email: Optional[str],
    phone: Optional[str],
    email_attempted: bool,
    phone_attempted: bool,
) -> bool:
    """Persist revealed contact info and mark lookup as attempted.

    Both email_attempted and phone_attempted are set in one DB write because
    a single PDL call returns both fields — no reason to bill twice.

    Args:
        conn: Database connection.
        name_key: The dedup key (lowercase "first_last").
        email: Email address returned by PDL, or None if not found.
        phone: Phone number returned by PDL, or None if not found.
        email_attempted: True once PDL has been queried for email (success or empty).
        phone_attempted: True once PDL has been queried for phone (success or empty).

    Returns:
        True if a row was updated, False if no matching lead found.
    """
    now = _sql_now()
    q = _placeholder_query(
        f"UPDATE leads SET email = %s, phone = %s, "
        "email_reveal_attempted = %s, phone_reveal_attempted = %s, "
        f"updated_at = {now} WHERE name_key = %s"
    )
    cur = _cursor(conn)
    try:
        cur.execute(
            q,
            (email, phone, int(email_attempted), int(phone_attempted), name_key),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
