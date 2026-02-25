"""SQLite persistence layer for Veranda leads.

Think of this module as a filing cabinet for all the leads Veranda discovers.
Instead of fetching thousands of records from live APIs every time you click
"Generate Leads," we save them here once and query them instantly afterward.

The database stores leads in a single table with deduplication by name — if
the same person appears from multiple sources, we keep the record with the
highest estimated wealth.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.lead import Lead, LeadSource, OutreachStatus

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "veranda.db",
)

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


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with row factory enabled.

    Args:
        db_path: Path to the database file. Defaults to data/veranda.db.
                 Use ":memory:" for in-memory databases (tests).

    Returns:
        A sqlite3.Connection with Row factory so columns are accessible by name.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist.

    This is idempotent — safe to call every time the app starts.
    """
    conn.executescript(SCHEMA_SQL)
    logger.info("Database schema initialized")


def _make_name_key(first_name: str, last_name: str) -> str:
    """Build a dedup key from first and last name."""
    return f"{first_name}_{last_name}".lower().strip("_")


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


def _row_to_lead(row: sqlite3.Row) -> Lead:
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


def save_leads(conn: sqlite3.Connection, leads: list[Lead]) -> int:
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
    cursor = conn.cursor()

    try:
        for lead in leads:
            row = _lead_to_row(lead)
            name_key = row["name_key"]

            existing = cursor.execute(
                "SELECT id, estimated_wealth FROM leads WHERE name_key = ?",
                (name_key,),
            ).fetchone()

            if existing is None:
                columns = ", ".join(row.keys())
                placeholders = ", ".join(f":{k}" for k in row.keys())
                cursor.execute(
                    f"INSERT INTO leads ({columns}) VALUES ({placeholders})",
                    row,
                )
                saved += 1
            else:
                incoming_wealth = row["estimated_wealth"] or 0
                existing_wealth = existing["estimated_wealth"] or 0
                if incoming_wealth > existing_wealth:
                    set_clause = ", ".join(
                        f"{k} = :{k}" for k in row.keys() if k != "name_key"
                    )
                    row["_id"] = existing["id"]
                    cursor.execute(
                        f"UPDATE leads SET {set_clause}, updated_at = datetime('now') "
                        f"WHERE id = :_id",
                        row,
                    )
                    saved += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    logger.info("Saved %d leads (of %d total)", saved, len(leads))
    return saved


def query_leads(
    conn: sqlite3.Connection,
    zip_codes: Optional[list[str]] = None,
    min_value: float = 0,
    residential_only: bool = False,
    individuals_only: bool = False,
    limit: Optional[int] = None,
) -> list[Lead]:
    """Query leads from the database with optional filters.

    Args:
        conn: Database connection.
        zip_codes: If provided, only return leads in these zip codes.
        min_value: Minimum estimated_wealth threshold.
        residential_only: If True, only return tax_assessor leads.
        individuals_only: If True, exclude leads with empty first_name (LLCs).
        limit: Maximum number of rows to return (applied at SQL level).

    Returns:
        List of Lead objects sorted by estimated_wealth descending.
    """
    conditions = []
    params: list = []

    if zip_codes:
        placeholders = ", ".join("?" for _ in zip_codes)
        conditions.append(f"zip_code IN ({placeholders})")
        params.extend(zip_codes)

    if min_value > 0:
        conditions.append("estimated_wealth >= ?")
        params.append(min_value)

    if residential_only:
        conditions.append("source = ?")
        params.append(LeadSource.TAX_ASSESSOR.value)

    if individuals_only:
        conditions.append("first_name != ''")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = f"LIMIT {limit}" if limit else ""

    rows = conn.execute(
        f"SELECT * FROM leads {where} ORDER BY estimated_wealth DESC {limit_clause}",
        params,
    ).fetchall()

    return [_row_to_lead(row) for row in rows]


def get_lead_count(conn: sqlite3.Connection) -> int:
    """Return total number of leads in the database."""
    result = conn.execute("SELECT COUNT(*) as cnt FROM leads").fetchone()
    return result["cnt"]


def get_last_sync(conn: sqlite3.Connection) -> Optional[str]:
    """Return the timestamp of the most recent completed sync, or None."""
    row = conn.execute(
        "SELECT completed_at FROM sync_log "
        "WHERE status = 'completed' "
        "ORDER BY completed_at DESC LIMIT 1"
    ).fetchone()
    return row["completed_at"] if row else None


def start_sync_log(
    conn: sqlite3.Connection, source: Optional[str] = None
) -> int:
    """Record the start of a sync run.

    Returns:
        The sync log ID for later updates.
    """
    cursor = conn.execute(
        "INSERT INTO sync_log (started_at, source, status) VALUES (?, ?, 'running')",
        (datetime.utcnow().isoformat(), source),
    )
    conn.commit()
    return cursor.lastrowid


def complete_sync_log(
    conn: sqlite3.Connection,
    sync_id: int,
    records_synced: int,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> None:
    """Record the end of a sync run."""
    conn.execute(
        "UPDATE sync_log SET completed_at = ?, records_synced = ?, "
        "status = ?, error_message = ? WHERE id = ?",
        (
            datetime.utcnow().isoformat(),
            records_synced,
            status,
            error_message,
            sync_id,
        ),
    )
    conn.commit()


def clear_leads(conn: sqlite3.Connection) -> int:
    """Delete all rows from the leads table.

    Use this to force a fresh live pull next time Generate Leads is clicked.

    Returns:
        Number of rows deleted.
    """
    cursor = conn.execute("DELETE FROM leads")
    conn.commit()
    logger.info("Cleared %d leads from database", cursor.rowcount)
    return cursor.rowcount


def update_outreach(
    conn: sqlite3.Connection,
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
    cursor = conn.execute(
        "UPDATE leads SET outreach_status = ?, outreach_draft = ?, "
        "updated_at = datetime('now') WHERE name_key = ?",
        (status, draft, name_key),
    )
    conn.commit()
    return cursor.rowcount > 0
