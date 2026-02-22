"""Tests for the Professional Mapping (Hunter.io) engine.

All API calls are mocked — no real Hunter requests are made during testing.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.engines.professional_mapping import (
    _extract_email_result,
    _get_hunter_key,
    enrich_lead_with_email,
    find_email,
    generate_search_links,
    verify_email,
)
from src.models.lead import Lead, LeadSource


# --- Sample Hunter.io API responses for mocking ---

SAMPLE_EMAIL_FINDER_RESPONSE = {
    "data": {
        "first_name": "Scott",
        "last_name": "Resnick",
        "email": "scott@resnickcapital.com",
        "confidence": 91,
        "position": "Managing Partner",
        "linkedin": "https://linkedin.com/in/scottresnick",
        "sources": [
            {"domain": "resnickcapital.com", "uri": "https://example.com/page1"},
            {"domain": "resnickcapital.com", "uri": "https://example.com/page2"},
        ],
    }
}

SAMPLE_EMAIL_FINDER_NO_EMAIL = {
    "data": {
        "first_name": "John",
        "last_name": "Doe",
        "email": None,
        "confidence": 0,
        "position": "",
        "linkedin": "",
        "sources": [],
    }
}

SAMPLE_EMAIL_VERIFIER_RESPONSE = {
    "data": {
        "email": "scott@resnickcapital.com",
        "status": "deliverable",
        "score": 92,
        "regexp": True,
        "smtp_server": True,
    }
}

SAMPLE_EMAIL_VERIFIER_RISKY = {
    "data": {
        "email": "maybe@example.com",
        "status": "risky",
        "score": 45,
        "regexp": True,
        "smtp_server": False,
    }
}


class TestGetHunterKey:
    """Test API key retrieval from environment."""

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {"HUNTER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="HUNTER_API_KEY is not set"):
                _get_hunter_key()

    def test_valid_key_returned(self):
        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key_123"}, clear=False):
            assert _get_hunter_key() == "test_key_123"

    def test_whitespace_only_key_raises(self):
        with patch.dict(os.environ, {"HUNTER_API_KEY": "   "}, clear=False):
            with pytest.raises(ValueError):
                _get_hunter_key()


class TestGenerateSearchLinks:
    """Test the free Google/LinkedIn search link generation."""

    def test_basic_links(self):
        links = generate_search_links("Scott", "Resnick")
        assert "google" in links
        assert "linkedin" in links
        assert "Scott+Resnick" in links["google"]
        assert "Scott+Resnick" in links["linkedin"]

    def test_google_does_not_include_linkedin_keyword(self):
        links = generate_search_links("John", "Smith")
        assert "linkedin" not in links["google"].lower()

    def test_google_name_only(self):
        links = generate_search_links("John", "Smith", address="123 W 10th St")
        assert "John+Smith" in links["google"]
        assert "123" not in links["google"]
        assert "New+York" not in links["google"]

    def test_linkedin_name_only(self):
        links = generate_search_links("Jane", "Doe", city="Brooklyn")
        assert "Jane+Doe" in links["linkedin"]
        assert "Brooklyn" not in links["linkedin"]

    def test_special_characters_encoded(self):
        links = generate_search_links("Mary", "O'Brien")
        # URL-encoded apostrophe
        assert "O%27Brien" in links["google"]

    def test_urls_are_valid(self):
        links = generate_search_links("Test", "Person")
        assert links["google"].startswith("https://www.google.com/search?q=")
        assert links["linkedin"].startswith("https://www.linkedin.com/search/results/people/")


class TestExtractEmailResult:
    """Test parsing of Hunter email finder response."""

    def test_full_result(self):
        data = SAMPLE_EMAIL_FINDER_RESPONSE["data"]
        result = _extract_email_result(data)

        assert result["email"] == "scott@resnickcapital.com"
        assert result["confidence"] == 91
        assert result["position"] == "Managing Partner"
        assert result["linkedin_url"] == "https://linkedin.com/in/scottresnick"
        assert result["sources"] == 2

    def test_no_email(self):
        data = SAMPLE_EMAIL_FINDER_NO_EMAIL["data"]
        result = _extract_email_result(data)
        assert result["email"] is None
        assert result["confidence"] == 0

    def test_empty_data(self):
        result = _extract_email_result({})
        assert result["email"] is None
        assert result["confidence"] == 0
        assert result["sources"] == 0

    def test_first_and_last_name_extracted(self):
        data = SAMPLE_EMAIL_FINDER_RESPONSE["data"]
        result = _extract_email_result(data)
        assert result["first_name"] == "Scott"
        assert result["last_name"] == "Resnick"


class TestFindEmail:
    """Test the find_email function with mocked HTTP calls."""

    @patch("src.engines.professional_mapping.httpx.get")
    def test_successful_find(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_FINDER_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key"}):
            result = find_email("Scott", "Resnick", "resnickcapital.com")

        assert result["email"] == "scott@resnickcapital.com"
        assert result["confidence"] == 91

    @patch("src.engines.professional_mapping.httpx.get")
    def test_no_email_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_FINDER_NO_EMAIL
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key"}):
            result = find_email("John", "Doe", "example.com")

        assert result["email"] is None

    @patch("src.engines.professional_mapping.httpx.get")
    def test_sends_correct_params(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_FINDER_NO_EMAIL
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "my_key"}):
            find_email("John", "Doe", "example.com")

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["api_key"] == "my_key"
        assert params["first_name"] == "John"
        assert params["last_name"] == "Doe"
        assert params["domain"] == "example.com"

    def test_empty_domain_raises(self):
        with pytest.raises(ValueError, match="domain is required"):
            find_email("Scott", "Resnick", "")

    def test_whitespace_domain_raises(self):
        with pytest.raises(ValueError):
            find_email("Scott", "Resnick", "   ")

    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {"HUNTER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError):
                find_email("Scott", "Resnick", "example.com")

    @patch("src.engines.professional_mapping.httpx.get")
    def test_domain_whitespace_stripped(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_FINDER_NO_EMAIL
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key"}):
            find_email("John", "Doe", "  example.com  ")

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["domain"] == "example.com"


class TestVerifyEmail:
    """Test the verify_email function with mocked HTTP calls."""

    @patch("src.engines.professional_mapping.httpx.get")
    def test_deliverable_email(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_VERIFIER_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key"}):
            result = verify_email("scott@resnickcapital.com")

        assert result["status"] == "deliverable"
        assert result["score"] == 92
        assert result["email"] == "scott@resnickcapital.com"

    @patch("src.engines.professional_mapping.httpx.get")
    def test_risky_email(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EMAIL_VERIFIER_RISKY
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"HUNTER_API_KEY": "test_key"}):
            result = verify_email("maybe@example.com")

        assert result["status"] == "risky"
        assert result["score"] == 45

    def test_verify_requires_api_key(self):
        with patch.dict(os.environ, {"HUNTER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError):
                verify_email("test@example.com")


class TestEnrichLeadWithEmail:
    """Test applying a found email to a Lead object."""

    def _make_lead(self) -> Lead:
        return Lead(
            first_name="Scott",
            last_name="Resnick",
            address="293 West 4 Street",
            city="New York",
            state="NY",
            zip_code="10014",
            estimated_wealth=23_674_734,
            discovery_trigger="Scott Resnick owns $23.7M property at 293 West 4 Street",
            source=LeadSource.TAX_ASSESSOR,
            confidence_score=0.7,
        )

    def test_email_added_to_lead(self):
        lead = self._make_lead()
        enriched = enrich_lead_with_email(lead, "scott@resnickcapital.com")
        assert enriched.email == "scott@resnickcapital.com"

    def test_empty_email_not_set(self):
        lead = self._make_lead()
        enriched = enrich_lead_with_email(lead, "")
        assert enriched.email is None

    def test_none_email_not_set(self):
        lead = self._make_lead()
        enriched = enrich_lead_with_email(lead, None)
        assert enriched.email is None

    def test_preserves_lead_source(self):
        lead = self._make_lead()
        enriched = enrich_lead_with_email(lead, "scott@resnickcapital.com")
        assert enriched.source == LeadSource.TAX_ASSESSOR

    def test_preserves_existing_fields(self):
        lead = self._make_lead()
        enriched = enrich_lead_with_email(lead, "scott@resnickcapital.com")
        assert enriched.first_name == "Scott"
        assert enriched.last_name == "Resnick"
        assert enriched.estimated_wealth == 23_674_734
