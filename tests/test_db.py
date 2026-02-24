"""Tests for the SQLite persistence layer (src/db.py).

All tests use in-memory SQLite databases for speed — no files are created
on disk during testing.
"""

import pytest
from datetime import datetime

from src.db import (
    get_connection,
    init_db,
    save_leads,
    query_leads,
    get_lead_count,
    get_last_sync,
    start_sync_log,
    complete_sync_log,
    update_outreach,
    _make_name_key,
    _lead_to_row,
    _row_to_lead,
)
from src.models.lead import Lead, LeadSource, OutreachStatus


# --- Fixtures ---

@pytest.fixture
def db():
    """Provide a fresh in-memory database for each test."""
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def _make_lead(**overrides) -> Lead:
    """Create a Lead with sensible defaults, overridable by kwargs."""
    defaults = {
        "first_name": "John",
        "last_name": "Doe",
        "discovery_trigger": "High-value property owner",
        "source": LeadSource.TAX_ASSESSOR,
        "estimated_wealth": 5_000_000.0,
        "zip_code": "10013",
        "address": "123 Broadway",
        "city": "New York",
        "state": "NY",
    }
    defaults.update(overrides)
    return Lead(**defaults)


# --- Schema Tests ---

class TestSchema:
    def test_init_db_creates_tables(self, db):
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "leads" in table_names
        assert "sync_log" in table_names

    def test_init_db_is_idempotent(self, db):
        """Calling init_db twice should not raise or duplicate tables."""
        init_db(db)
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='leads'"
        ).fetchone()
        assert count["cnt"] == 1

    def test_indexes_created(self, db):
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        index_names = {idx["name"] for idx in indexes}
        assert "idx_leads_name_key" in index_names
        assert "idx_leads_zip_code" in index_names
        assert "idx_leads_source" in index_names
        assert "idx_leads_estimated_wealth" in index_names


# --- Name Key Tests ---

class TestNameKey:
    def test_basic_name_key(self):
        assert _make_name_key("John", "Doe") == "john_doe"

    def test_empty_first_name(self):
        assert _make_name_key("", "SomeLLC") == "somellc"

    def test_mixed_case(self):
        assert _make_name_key("JANE", "Smith") == "jane_smith"


# --- Save & Dedup Tests ---

class TestSaveLeads:
    def test_save_single_lead(self, db):
        lead = _make_lead()
        saved = save_leads(db, [lead])
        assert saved == 1
        assert get_lead_count(db) == 1

    def test_save_multiple_leads(self, db):
        leads = [
            _make_lead(first_name="Alice", last_name="Smith"),
            _make_lead(first_name="Bob", last_name="Jones"),
        ]
        saved = save_leads(db, leads)
        assert saved == 2
        assert get_lead_count(db) == 2

    def test_dedup_keeps_higher_wealth(self, db):
        low = _make_lead(estimated_wealth=1_000_000.0)
        high = _make_lead(estimated_wealth=10_000_000.0)
        save_leads(db, [low])
        save_leads(db, [high])
        assert get_lead_count(db) == 1
        leads = query_leads(db)
        assert leads[0].estimated_wealth == 10_000_000.0

    def test_dedup_ignores_lower_wealth(self, db):
        high = _make_lead(estimated_wealth=10_000_000.0)
        low = _make_lead(estimated_wealth=1_000_000.0)
        save_leads(db, [high])
        saved = save_leads(db, [low])
        assert saved == 0
        leads = query_leads(db)
        assert leads[0].estimated_wealth == 10_000_000.0

    def test_save_empty_list(self, db):
        saved = save_leads(db, [])
        assert saved == 0
        assert get_lead_count(db) == 0


# --- Query Tests ---

class TestQueryLeads:
    def test_query_all(self, db):
        save_leads(db, [
            _make_lead(first_name="Alice", last_name="A", estimated_wealth=1_000_000),
            _make_lead(first_name="Bob", last_name="B", estimated_wealth=5_000_000),
        ])
        leads = query_leads(db)
        assert len(leads) == 2
        assert leads[0].estimated_wealth > leads[1].estimated_wealth

    def test_query_by_zip_code(self, db):
        save_leads(db, [
            _make_lead(first_name="Alice", last_name="A", zip_code="10013"),
            _make_lead(first_name="Bob", last_name="B", zip_code="11201"),
        ])
        leads = query_leads(db, zip_codes=["10013"])
        assert len(leads) == 1
        assert leads[0].first_name == "Alice"

    def test_query_min_value(self, db):
        save_leads(db, [
            _make_lead(first_name="Low", last_name="L", estimated_wealth=500_000),
            _make_lead(first_name="High", last_name="H", estimated_wealth=5_000_000),
        ])
        leads = query_leads(db, min_value=1_000_000)
        assert len(leads) == 1
        assert leads[0].first_name == "High"

    def test_query_individuals_only(self, db):
        save_leads(db, [
            _make_lead(first_name="Alice", last_name="Smith"),
            _make_lead(first_name="", last_name="SomeLLC", company="SomeLLC"),
        ])
        leads = query_leads(db, individuals_only=True)
        assert len(leads) == 1
        assert leads[0].first_name == "Alice"

    def test_query_residential_only(self, db):
        save_leads(db, [
            _make_lead(first_name="Prop", last_name="Owner", source=LeadSource.TAX_ASSESSOR),
            _make_lead(first_name="Insider", last_name="Trader", source=LeadSource.SEC_EDGAR),
        ])
        leads = query_leads(db, residential_only=True)
        assert len(leads) == 1
        assert leads[0].source == LeadSource.TAX_ASSESSOR

    def test_query_empty_db(self, db):
        leads = query_leads(db)
        assert leads == []

    def test_query_multiple_zip_codes(self, db):
        save_leads(db, [
            _make_lead(first_name="A", last_name="A", zip_code="10013"),
            _make_lead(first_name="B", last_name="B", zip_code="11201"),
            _make_lead(first_name="C", last_name="C", zip_code="10001"),
        ])
        leads = query_leads(db, zip_codes=["10013", "11201"])
        assert len(leads) == 2


# --- Round-trip Tests ---

class TestRoundTrip:
    def test_lead_survives_roundtrip(self, db):
        original = _make_lead(
            first_name="Jane",
            last_name="Doe",
            city="New York",
            state="NY",
            zip_code="10013",
            address="456 West St",
            professional_title="CEO",
            company="Acme Inc",
            estimated_wealth=8_000_000.0,
            year_built=1920,
            num_floors=4,
            building_area=3500,
            lot_area=2000,
            building_type="Brownstone",
            unit_number="3A",
            deed_sale_amount=6_500_000.0,
            deed_date="2024-06-15",
            source=LeadSource.TAX_ASSESSOR,
            confidence_score=0.85,
        )
        save_leads(db, [original])
        result = query_leads(db)[0]
        assert result.first_name == original.first_name
        assert result.last_name == original.last_name
        assert result.estimated_wealth == original.estimated_wealth
        assert result.year_built == original.year_built
        assert result.building_type == original.building_type
        assert result.deed_sale_amount == original.deed_sale_amount
        assert result.source == original.source
        assert result.confidence_score == original.confidence_score


# --- Sync Log Tests ---

class TestSyncLog:
    def test_start_and_complete_sync(self, db):
        sync_id = start_sync_log(db, source="all")
        assert sync_id is not None
        assert get_last_sync(db) is None  # not completed yet

        complete_sync_log(db, sync_id, records_synced=150)
        last = get_last_sync(db)
        assert last is not None

    def test_failed_sync_not_returned_by_get_last_sync(self, db):
        sync_id = start_sync_log(db)
        complete_sync_log(db, sync_id, records_synced=0, status="failed", error_message="API down")
        assert get_last_sync(db) is None

    def test_multiple_syncs_returns_latest(self, db):
        s1 = start_sync_log(db)
        complete_sync_log(db, s1, records_synced=100)
        first_sync = get_last_sync(db)

        s2 = start_sync_log(db)
        complete_sync_log(db, s2, records_synced=200)
        second_sync = get_last_sync(db)

        assert second_sync >= first_sync


# --- Outreach Tests ---

class TestOutreach:
    def test_update_outreach(self, db):
        save_leads(db, [_make_lead()])
        updated = update_outreach(db, "john_doe", "draft_ready", "Hello John!")
        assert updated is True
        leads = query_leads(db)
        assert leads[0].outreach_status == OutreachStatus.DRAFT_READY
        assert leads[0].outreach_draft == "Hello John!"

    def test_update_outreach_no_match(self, db):
        updated = update_outreach(db, "nobody_here", "draft_ready", "Hello!")
        assert updated is False
