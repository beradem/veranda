"""Tests for the FEC Campaign Finance engine."""

import pytest
from unittest.mock import patch, MagicMock

from src.engines.fec import (
    _build_discovery_trigger,
    _calculate_confidence,
    _parse_fec_name,
    _process_single_record,
    fetch_fec_donors,
)
from src.models.lead import Lead, LeadSource


class TestParseFecName:
    """Test name parsing from FEC's LAST, FIRST format."""

    def test_standard_last_comma_first(self):
        assert _parse_fec_name("SMITH, JOHN") == ("John", "Smith")

    def test_last_comma_first_middle(self):
        first, last = _parse_fec_name("SMITH, JOHN MICHAEL")
        assert first == "John"
        assert last == "Smith"

    def test_title_case_applied(self):
        first, last = _parse_fec_name("JOHNSON, EMILY")
        assert first == "Emily"
        assert last == "Johnson"

    def test_no_comma_space_separated(self):
        first, last = _parse_fec_name("John Smith")
        assert first == "John"
        assert last == "Smith"

    def test_single_name_no_comma(self):
        first, last = _parse_fec_name("Madonna")
        assert first == "Madonna"
        assert last == ""

    def test_empty_string(self):
        assert _parse_fec_name("") == ("Unknown", "Unknown")

    def test_whitespace_only(self):
        assert _parse_fec_name("   ") == ("Unknown", "Unknown")


class TestBuildDiscoveryTrigger:
    """Test the human-readable trigger string generation."""

    def test_includes_name_and_amount(self):
        trigger = _build_discovery_trigger(
            donor_name="John Smith",
            amount=10_000.0,
            employer="Acme Capital",
            occupation="CEO",
            contribution_date="2025-10-15",
        )
        assert "John Smith" in trigger
        assert "$10,000" in trigger
        assert "2025-10-15" in trigger

    def test_includes_occupation_and_employer(self):
        trigger = _build_discovery_trigger(
            donor_name="Jane Doe",
            amount=5_000.0,
            employer="Goldcrest Partners",
            occupation="Managing Partner",
            contribution_date="2025-11-01",
        )
        assert "Managing Partner" in trigger
        assert "Goldcrest Partners" in trigger

    def test_empty_employer_and_occupation(self):
        trigger = _build_discovery_trigger(
            donor_name="Bob",
            amount=2_500.0,
            employer="",
            occupation="",
            contribution_date="2025-09-01",
        )
        assert "Bob" in trigger
        assert "$2,500" in trigger


class TestCalculateConfidence:
    """Test confidence scoring logic."""

    def test_high_value_ceo(self):
        score = _calculate_confidence(50_000.0, "CEO", "Some Corp")
        assert score >= 0.8

    def test_medium_value_partner(self):
        score = _calculate_confidence(10_000.0, "Managing Partner", "Private Equity LLC")
        assert 0.5 <= score <= 0.9

    def test_physician_mid_donation(self):
        score = _calculate_confidence(5_000.0, "Physician", "NYU Medical")
        assert score >= 0.4

    def test_minimum_donation_baseline(self):
        score = _calculate_confidence(2_500.0, "", "")
        assert score >= 0.3  # value tier + baseline

    def test_score_never_exceeds_one(self):
        score = _calculate_confidence(999_999.0, "Chairman and CEO", "MegaCorp")
        assert score <= 1.0

    def test_score_always_positive(self):
        score = _calculate_confidence(100.0, "", "")
        assert score >= 0.1  # baseline always applied


class TestProcessSingleRecord:
    """Test parsing individual FEC API response records."""

    def _make_record(self, **overrides) -> dict:
        base = {
            "contributor_name": "SMITH, JOHN",
            "contribution_receipt_amount": 10000.0,
            "contribution_receipt_date": "2025-10-01",
            "contributor_city": "MIAMI",
            "contributor_state": "FL",
            "contributor_zip": "33101",
            "contributor_employer": "Smith Capital",
            "contributor_occupation": "CEO",
        }
        base.update(overrides)
        return base

    def test_valid_record_returns_lead(self):
        lead = _process_single_record(self._make_record())
        assert lead is not None
        assert isinstance(lead, Lead)
        assert lead.source == LeadSource.FEC_CAMPAIGN_FINANCE

    def test_name_parsed_correctly(self):
        lead = _process_single_record(self._make_record())
        assert lead.first_name == "John"
        assert lead.last_name == "Smith"

    def test_location_fields_populated(self):
        lead = _process_single_record(self._make_record())
        assert lead.city == "Miami"
        assert lead.state == "FL"
        assert lead.zip_code == "33101"

    def test_professional_fields_populated(self):
        lead = _process_single_record(self._make_record())
        assert lead.professional_title == "CEO"
        assert lead.company == "Smith Capital"

    def test_estimated_wealth_is_donation_amount(self):
        lead = _process_single_record(self._make_record(contribution_receipt_amount=25_000.0))
        assert lead.estimated_wealth == 25_000.0

    def test_zip_code_truncated_to_five_digits(self):
        lead = _process_single_record(self._make_record(contributor_zip="331010000"))
        assert lead.zip_code == "33101"

    def test_missing_name_returns_none(self):
        assert _process_single_record(self._make_record(contributor_name="")) is None

    def test_missing_amount_returns_none(self):
        assert _process_single_record(self._make_record(contribution_receipt_amount=None)) is None

    def test_whitespace_name_returns_none(self):
        assert _process_single_record(self._make_record(contributor_name="   ")) is None


class TestFetchFecDonors:
    """Test the main fetch function with a mocked HTTP client."""

    def _make_api_response(self, records: list[dict]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": records, "pagination": {"count": len(records)}}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def _sample_record(self) -> dict:
        return {
            "contributor_name": "JONES, PATRICIA",
            "contribution_receipt_amount": 5000.0,
            "contribution_receipt_date": "2025-09-15",
            "contributor_city": "AUSTIN",
            "contributor_state": "TX",
            "contributor_zip": "78701",
            "contributor_employer": "Jones Ventures",
            "contributor_occupation": "Founder",
        }

    @patch("src.engines.fec.httpx.get")
    def test_returns_leads_on_success(self, mock_get):
        mock_get.return_value = self._make_api_response([self._sample_record()])
        leads = fetch_fec_donors(min_donation=2_500.0, max_results=10)
        assert len(leads) == 1
        assert leads[0].source == LeadSource.FEC_CAMPAIGN_FINANCE

    @patch("src.engines.fec.httpx.get")
    def test_empty_results_returns_empty_list(self, mock_get):
        mock_get.return_value = self._make_api_response([])
        leads = fetch_fec_donors()
        assert leads == []

    @patch("src.engines.fec.httpx.get")
    def test_http_error_returns_empty_list(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.RequestError("connection failed")
        leads = fetch_fec_donors()
        assert leads == []

    @patch("src.engines.fec.httpx.get")
    def test_state_filter_passed_to_api(self, mock_get):
        mock_get.return_value = self._make_api_response([])
        fetch_fec_donors(state="NY")
        call_params = mock_get.call_args[1]["params"]
        assert call_params["contributor_state"] == "NY"

    @patch("src.engines.fec.httpx.get")
    def test_malformed_records_skipped_gracefully(self, mock_get):
        bad_record = {"contributor_name": "BROKEN", "contribution_receipt_amount": None}
        good_record = self._sample_record()
        mock_get.return_value = self._make_api_response([bad_record, good_record])
        leads = fetch_fec_donors()
        # Only the valid record becomes a lead
        assert len(leads) == 1

    @patch("src.engines.fec.httpx.get")
    def test_max_results_respected(self, mock_get):
        records = [self._sample_record() for _ in range(10)]
        mock_get.return_value = self._make_api_response(records)
        leads = fetch_fec_donors(max_results=3)
        assert len(leads) <= 3
