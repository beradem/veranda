"""Tests for the Outreach Generator (Gemini integration)."""

from unittest.mock import patch, MagicMock

import pytest

from src.engines.outreach_generator import (
    _get_era_description,
    _build_outreach_prompt,
    _get_llm_key,
    generate_outreach_for_lead,
    parse_lead_criteria,
    PARSE_CRITERIA_DEFAULTS,
)
from src.models.lead import Lead, LeadSource


# --- Fixtures ---

def _make_lead(**overrides) -> Lead:
    """Create a test Lead with sensible defaults."""
    defaults = {
        "first_name": "John",
        "last_name": "Smith",
        "address": "123 W 10th St",
        "city": "New York",
        "state": "NY",
        "zip_code": "10014",
        "estimated_wealth": 8_200_000,
        "discovery_trigger": "John Smith owns $8.2M property at 123 W 10th St, West Village",
        "source": LeadSource.TAX_ASSESSOR,
        "confidence_score": 0.7,
        "year_built": 1920,
        "num_floors": 4,
        "building_area": 3500,
        "lot_area": 2000,
        "building_type": "One Family Attached",
    }
    defaults.update(overrides)
    return Lead(**defaults)


SERVICE_DESC = "Boutique interior design firm specializing in pre-war brownstone renovations."
IDEAL_CLIENT = "Owners of pre-war brownstones valued at $3M+ in the West Village."


# =========================================================================
# _get_era_description
# =========================================================================

class TestGetEraDescription:
    """Test year-to-era mapping."""

    def test_historic(self):
        assert _get_era_description(1885) == "historic"

    def test_pre_war(self):
        assert _get_era_description(1920) == "pre-war"

    def test_pre_war_boundary(self):
        assert _get_era_description(1939) == "pre-war"

    def test_mid_century(self):
        assert _get_era_description(1955) == "mid-century"

    def test_mid_century_boundary(self):
        assert _get_era_description(1940) == "mid-century"

    def test_post_war(self):
        assert _get_era_description(1970) == "post-war"

    def test_post_war_boundary(self):
        assert _get_era_description(1960) == "post-war"

    def test_contemporary(self):
        assert _get_era_description(1995) == "contemporary"

    def test_contemporary_boundary(self):
        assert _get_era_description(1980) == "contemporary"

    def test_modern(self):
        assert _get_era_description(2015) == "modern"

    def test_modern_boundary(self):
        assert _get_era_description(2000) == "modern"

    def test_none_year(self):
        assert _get_era_description(None) == "unknown era"


# =========================================================================
# _build_outreach_prompt
# =========================================================================

class TestBuildOutreachPrompt:
    """Test prompt construction."""

    def test_full_context_includes_all_fields(self):
        lead = _make_lead()
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)

        assert "John Smith" in prompt
        assert "$8.2M" in prompt
        assert "One Family Attached" in prompt
        assert "1920" in prompt
        assert "pre-war" in prompt
        assert "3,500 sq ft" in prompt
        assert "2,000 sq ft" in prompt
        assert "4" in prompt  # floors
        assert "123 W 10th St" in prompt
        assert SERVICE_DESC in prompt
        assert IDEAL_CLIENT in prompt

    def test_minimal_data_still_works(self):
        lead = _make_lead(
            year_built=None,
            num_floors=None,
            building_area=None,
            lot_area=None,
            building_type=None,
        )
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)

        assert "John Smith" in prompt
        assert "$8.2M" in prompt
        assert "123 W 10th St" in prompt

    def test_sub_million_value_formatting(self):
        lead = _make_lead(estimated_wealth=750_000)
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)
        assert "$750,000" in prompt

    def test_prompt_contains_rules(self):
        lead = _make_lead()
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)

        assert "2 sentences" in prompt
        assert "Do NOT use cliches" in prompt
        assert "Hi John," in prompt

    def test_prompt_contains_format_structure(self):
        lead = _make_lead()
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)

        assert "FORMAT" in prompt
        assert "introduce who you are" in prompt
        assert "low-pressure close" in prompt

    def test_empty_name_uses_fallback(self):
        lead = _make_lead(first_name="", last_name="")
        prompt = _build_outreach_prompt(lead, SERVICE_DESC, IDEAL_CLIENT)
        assert "the homeowner" in prompt
        assert "Hi there," in prompt


# =========================================================================
# generate_outreach_for_lead
# =========================================================================

class TestGenerateOutreachForLead:
    """Test single-lead outreach generation with mocked Groq REST API."""

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_success(self, mock_post, mock_key):
        """Successful Groq call populates outreach_draft."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Your pre-war brownstone on W 10th St would shine with updated interiors."
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        lead = _make_lead()
        result = generate_outreach_for_lead(lead, SERVICE_DESC, IDEAL_CLIENT)

        assert result.outreach_draft is not None
        assert "brownstone" in result.outreach_draft
        mock_post.assert_called_once()

    @patch("src.engines.outreach_generator._get_llm_key", return_value=None)
    def test_no_api_key_returns_unchanged(self, mock_key):
        """Without API key, lead is returned with no outreach_draft."""
        lead = _make_lead()
        result = generate_outreach_for_lead(lead, SERVICE_DESC, IDEAL_CLIENT)
        assert result.outreach_draft is None

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_api_error_returns_unchanged(self, mock_post, mock_key):
        """If API throws an error, lead is returned without outreach."""
        mock_post.side_effect = Exception("API quota exceeded")

        lead = _make_lead()
        result = generate_outreach_for_lead(lead, SERVICE_DESC, IDEAL_CLIENT)
        assert result.outreach_draft is None


# =========================================================================
# parse_lead_criteria
# =========================================================================

class TestParsLeadCriteria:
    """Test AI-powered lead criteria extraction."""

    @patch("src.engines.outreach_generator._get_llm_key", return_value=None)
    def test_no_api_key_returns_defaults(self, mock_key):
        """Without API key, sensible defaults are returned."""
        result = parse_lead_criteria("luxury kitchen remodeling in Brooklyn")
        assert result == PARSE_CRITERIA_DEFAULTS

    def test_empty_description_returns_defaults(self):
        """Empty input returns defaults regardless of API key."""
        with patch("src.engines.outreach_generator._get_llm_key", return_value="fake"):
            result = parse_lead_criteria("   ")
        assert result == PARSE_CRITERIA_DEFAULTS

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_successful_parse(self, mock_post, mock_key):
        """Successful Groq call returns parsed criteria."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"neighborhoods": ["Park Slope", "Brooklyn Heights"], '
                               '"min_value": 3000000, "residential_only": true, '
                               '"individuals_only": true, "include_condos": false}'
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = parse_lead_criteria("high-end kitchen remodeling in Brooklyn")

        assert result["neighborhoods"] == ["Park Slope", "Brooklyn Heights"]
        assert result["min_value"] == 3_000_000
        assert result["residential_only"] is True
        assert result["include_condos"] is False

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_markdown_code_fences_stripped(self, mock_post, mock_key):
        """Groq sometimes wraps JSON in ```json ... ``` — we handle that."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"neighborhoods": ["Tribeca"], '
                               '"min_value": 5000000, "residential_only": false, '
                               '"individuals_only": true, "include_condos": true}\n```'
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = parse_lead_criteria("commercial cleaning for office buildings in Tribeca")

        assert result["neighborhoods"] == ["Tribeca"]
        assert result["min_value"] == 5_000_000
        assert result["residential_only"] is False

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_invalid_neighborhoods_use_defaults(self, mock_post, mock_key):
        """If Groq returns neighborhood names not in our list, fall back to defaults."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"neighborhoods": ["Beverly Hills", "Malibu"], '
                               '"min_value": 10000000, "residential_only": true, '
                               '"individuals_only": true, "include_condos": true}'
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = parse_lead_criteria("luxury services in Los Angeles")

        assert result["neighborhoods"] == PARSE_CRITERIA_DEFAULTS["neighborhoods"]
        assert result["min_value"] == 10_000_000

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_api_error_returns_defaults(self, mock_post, mock_key):
        """If the API call fails, return defaults."""
        mock_post.side_effect = Exception("Connection timeout")

        result = parse_lead_criteria("luxury kitchen remodeling in Brooklyn")
        assert result == PARSE_CRITERIA_DEFAULTS

    @patch("src.engines.outreach_generator._get_llm_key", return_value="fake-key")
    @patch("src.engines.outreach_generator.httpx.post")
    def test_malformed_json_returns_defaults(self, mock_post, mock_key):
        """If Groq returns invalid JSON, return defaults."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {"content": "I'd recommend searching Park Slope and..."}
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = parse_lead_criteria("luxury services")
        assert result == PARSE_CRITERIA_DEFAULTS
