"""Tests for the SEC EDGAR Form 4 engine."""

import pytest

from src.engines.sec_edgar import (
    _build_discovery_trigger,
    _calculate_confidence,
    _parse_insider_name,
)
from src.models.lead import Lead, LeadSource


class TestParseInsiderName:
    """Test name parsing from EDGAR's various formats."""

    def test_standard_two_part_name(self):
        assert _parse_insider_name("John Smith") == ("John", "Smith")

    def test_all_caps_last_first(self):
        """EDGAR often gives names as 'SMITH JOHN'."""
        assert _parse_insider_name("SMITH JOHN") == ("John", "Smith")

    def test_three_part_name(self):
        first, last = _parse_insider_name("John Michael Smith")
        assert first == "John"
        assert last == "Smith"

    def test_single_name(self):
        assert _parse_insider_name("Madonna") == ("Madonna", "")

    def test_empty_string(self):
        assert _parse_insider_name("") == ("Unknown", "Unknown")

    def test_whitespace_only(self):
        assert _parse_insider_name("   ") == ("Unknown", "Unknown")


class TestBuildDiscoveryTrigger:
    """Test the human-readable trigger string generation."""

    def test_basic_trigger(self):
        from datetime import date

        trigger = _build_discovery_trigger(
            insider_name="Jane Doe",
            company_name="Apple Inc.",
            ticker="AAPL",
            total_value=5_200_000.0,
            filing_date=date(2025, 6, 15),
        )
        assert "Jane Doe" in trigger
        assert "$5,200,000" in trigger
        assert "Apple Inc." in trigger
        assert "AAPL" in trigger
        assert "2025-06-15" in trigger


class TestCalculateConfidence:
    """Test the confidence scoring logic."""

    def test_high_value_ceo(self):
        score = _calculate_confidence(15_000_000, "Chief Executive Officer")
        assert score >= 0.8

    def test_medium_value_director(self):
        score = _calculate_confidence(3_000_000, "Director")
        assert 0.4 <= score <= 0.7

    def test_minimum_qualifying_sale(self):
        score = _calculate_confidence(1_000_000, "")
        assert score >= 0.3  # base value tier + baseline

    def test_score_never_exceeds_one(self):
        score = _calculate_confidence(100_000_000, "CEO and President")
        assert score <= 1.0

    def test_score_always_positive(self):
        score = _calculate_confidence(500, "")
        assert score >= 0.1  # baseline


class TestLeadModel:
    """Test the Lead data model itself."""

    def test_create_valid_lead(self):
        lead = Lead(
            first_name="John",
            last_name="Doe",
            discovery_trigger="Sold $5M in AAPL stock",
            source=LeadSource.SEC_EDGAR,
        )
        assert lead.full_name == "John Doe"
        assert lead.outreach_status.value == "pending"
        assert lead.confidence_score == 0.0

    def test_confidence_score_bounds(self):
        with pytest.raises(ValueError):
            Lead(
                first_name="John",
                last_name="Doe",
                discovery_trigger="test",
                source=LeadSource.SEC_EDGAR,
                confidence_score=1.5,  # over max
            )

        with pytest.raises(ValueError):
            Lead(
                first_name="John",
                last_name="Doe",
                discovery_trigger="test",
                source=LeadSource.SEC_EDGAR,
                confidence_score=-0.1,  # under min
            )

    def test_lead_source_enum(self):
        assert LeadSource.SEC_EDGAR.value == "sec_edgar"
        assert LeadSource.TAX_ASSESSOR.value == "tax_assessor"
