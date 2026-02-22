"""Tests for the Real Estate (NYC PLUTO) engine."""

import pytest

from src.engines.real_estate import (
    _build_discovery_trigger,
    _calculate_confidence,
    _derive_tax_class,
    _estimate_market_value,
    _parse_owner_name,
    _zip_to_neighborhood,
    _build_address,
    NEIGHBORHOOD_ZIP_CODES,
    TAX_CLASS_MULTIPLIERS,
)
from src.models.lead import Lead, LeadSource


class TestDeriveTaxClass:
    """Test building class to tax class mapping."""

    def test_single_family_a(self):
        assert _derive_tax_class("A5") == "1"

    def test_single_family_b(self):
        assert _derive_tax_class("B3") == "1"

    def test_walkup_apartment_c(self):
        assert _derive_tax_class("C0") == "2"

    def test_elevator_apartment_d(self):
        assert _derive_tax_class("D4") == "2"

    def test_condo_r(self):
        assert _derive_tax_class("R4") == "2"

    def test_commercial_o(self):
        assert _derive_tax_class("O5") == "4"

    def test_empty_defaults_to_commercial(self):
        assert _derive_tax_class("") == "4"


class TestEstimateMarketValue:
    """Test the market value estimation from assessed value + building class."""

    def test_single_family_home(self):
        """A-class (1-3 family) assessed at ~6%, multiplier is ~16.67x."""
        result = _estimate_market_value(300_000, "A5")
        assert result == pytest.approx(300_000 * 16.67, rel=0.01)

    def test_apartment_building(self):
        """D-class (elevator apartment) assessed at ~45%, multiplier ~2.22x."""
        result = _estimate_market_value(1_000_000, "D4")
        assert result == pytest.approx(1_000_000 * 2.22, rel=0.01)

    def test_condo(self):
        """R-class (condo) assessed at ~45%, multiplier ~2.22x."""
        result = _estimate_market_value(2_000_000, "R4")
        assert result == pytest.approx(2_000_000 * 2.22, rel=0.01)

    def test_commercial(self):
        """O-class (commercial) → tax class 4, multiplier ~2.22x."""
        result = _estimate_market_value(2_000_000, "O5")
        assert result == pytest.approx(2_000_000 * 2.22, rel=0.01)

    def test_unknown_class_uses_commercial_default(self):
        """Unknown building class defaults to commercial (tax class 4)."""
        result = _estimate_market_value(1_000_000, "Z9")
        assert result == pytest.approx(1_000_000 * 2.22, rel=0.01)

    def test_empty_class_uses_default(self):
        result = _estimate_market_value(1_000_000, "")
        assert result == pytest.approx(1_000_000 * 2.22, rel=0.01)

    def test_zero_assessed_value(self):
        result = _estimate_market_value(0, "A5")
        assert result == 0.0


class TestParseOwnerName:
    """Test owner name parsing and LLC detection."""

    def test_comma_separated_last_first(self):
        """Standard property record format: 'SMITH, JOHN'."""
        first, last, is_llc = _parse_owner_name("SMITH, JOHN")
        assert first == "John"
        assert last == "Smith"
        assert is_llc is False

    def test_space_separated_last_first(self):
        """Space-only format: 'SMITH JOHN'."""
        first, last, is_llc = _parse_owner_name("SMITH JOHN")
        assert first == "John"
        assert last == "Smith"
        assert is_llc is False

    def test_single_name(self):
        first, last, is_llc = _parse_owner_name("MADONNA")
        assert first == "Madonna"
        assert last == ""
        assert is_llc is False

    def test_empty_string(self):
        first, last, is_llc = _parse_owner_name("")
        assert first == "Unknown"
        assert last == "Unknown"
        assert is_llc is False

    def test_whitespace_only(self):
        first, last, is_llc = _parse_owner_name("   ")
        assert first == "Unknown"
        assert last == "Unknown"
        assert is_llc is False

    def test_llc_detected(self):
        first, last, is_llc = _parse_owner_name("123 BROADWAY LLC")
        assert is_llc is True
        assert first == ""
        assert "Broadway" in last

    def test_trust_detected(self):
        first, last, is_llc = _parse_owner_name("SMITH FAMILY TRUST")
        assert is_llc is True

    def test_inc_detected(self):
        first, last, is_llc = _parse_owner_name("ACME HOLDINGS INC")
        assert is_llc is True

    def test_corp_detected(self):
        first, last, is_llc = _parse_owner_name("MANHATTAN REALTY CORP")
        assert is_llc is True

    def test_normal_name_not_flagged(self):
        """Make sure regular names don't trigger LLC detection."""
        _, _, is_llc = _parse_owner_name("JONES, MICHAEL")
        assert is_llc is False

    def test_comma_format_with_middle_name(self):
        """'SMITH, JOHN PAUL' — first name should be 'John'."""
        first, last, is_llc = _parse_owner_name("SMITH, JOHN PAUL")
        assert first == "John"
        assert last == "Smith"
        assert is_llc is False

    def test_unavailable_owner_flagged(self):
        _, _, is_llc = _parse_owner_name("UNAVAILABLE OWNER")
        assert is_llc is True

    def test_government_flagged(self):
        _, _, is_llc = _parse_owner_name("DEPARTMENT NYC")
        assert is_llc is True

    def test_embassy_flagged(self):
        _, _, is_llc = _parse_owner_name("REPUBLIC OF ITALY")
        assert is_llc is True

    def test_museum_flagged(self):
        _, _, is_llc = _parse_owner_name("MUSEUM WHITNEY")
        assert is_llc is True

    def test_holy_see_flagged(self):
        _, _, is_llc = _parse_owner_name("THE HOLY SEE")
        assert is_llc is True

    def test_investments_flagged(self):
        _, _, is_llc = _parse_owner_name("DREFIN INVESTMENTS LIMITED")
        assert is_llc is True

    def test_address_as_name_flagged(self):
        """Street addresses used as owner names should be flagged."""
        _, _, is_llc = _parse_owner_name("18 EAST 71ST STREET")
        assert is_llc is True

    def test_country_name_flagged(self):
        _, _, is_llc = _parse_owner_name("IRAN")
        assert is_llc is True

    def test_number_prefixed_name_flagged(self):
        """Names starting with numbers are addresses or entity codes."""
        _, _, is_llc = _parse_owner_name("145 READE")
        assert is_llc is True

    def test_diplomatic_mission_flagged(self):
        _, _, is_llc = _parse_owner_name("MISSION OF BRAZIL")
        assert is_llc is True

    def test_trustee_prefix_stripped(self):
        """'HOWARD W. LUTNICK, AS TRUSTEE' should parse to the person's name."""
        first, last, is_llc = _parse_owner_name("LUTNICK, HOWARD W. AS TRUSTEE")
        assert is_llc is False
        assert first == "Howard"
        assert last == "Lutnick"

    def test_trustee_prefix_stripped_no_comma(self):
        first, last, is_llc = _parse_owner_name("HOWARD W. LUTNICK AS TRUSTEE")
        assert is_llc is False
        assert first == "W."
        assert last == "Howard"


class TestCalculateConfidence:
    """Test the confidence scoring logic."""

    def test_high_value_residential(self):
        """$10M+ residential property — should be high confidence."""
        score = _calculate_confidence(12_000_000, is_llc=False, building_class="A5")
        assert score >= 0.7

    def test_medium_value_residential(self):
        score = _calculate_confidence(3_000_000, is_llc=False, building_class="B2")
        assert 0.4 <= score <= 0.8

    def test_llc_penalty(self):
        """LLC owners should get lower confidence than named individuals."""
        score_person = _calculate_confidence(5_000_000, is_llc=False, building_class="A1")
        score_llc = _calculate_confidence(5_000_000, is_llc=True, building_class="A1")
        assert score_llc < score_person

    def test_residential_bonus(self):
        """Residential building classes should score higher than commercial."""
        score_residential = _calculate_confidence(5_000_000, is_llc=False, building_class="A1")
        score_commercial = _calculate_confidence(5_000_000, is_llc=False, building_class="O5")
        assert score_residential > score_commercial

    def test_score_never_exceeds_one(self):
        score = _calculate_confidence(100_000_000, is_llc=False, building_class="A1")
        assert score <= 1.0

    def test_score_never_below_zero(self):
        """Even with LLC penalty, score should not go below zero."""
        score = _calculate_confidence(500_000, is_llc=True, building_class="O1")
        assert score >= 0.0

    def test_minimum_qualifying_property(self):
        score = _calculate_confidence(1_000_000, is_llc=False, building_class="")
        assert score >= 0.2

    def test_empty_building_class(self):
        """Should not crash on empty building class."""
        score = _calculate_confidence(5_000_000, is_llc=False, building_class="")
        assert 0.0 <= score <= 1.0


class TestBuildDiscoveryTrigger:
    """Test the human-readable trigger string generation."""

    def test_basic_trigger(self):
        trigger = _build_discovery_trigger(
            owner_name="John Smith",
            address="123 W 10th St",
            market_value=8_200_000,
            neighborhood="West Village",
        )
        assert "John Smith" in trigger
        assert "$8.2M" in trigger
        assert "123 W 10th St" in trigger
        assert "West Village" in trigger

    def test_sub_million_formatting(self):
        trigger = _build_discovery_trigger(
            owner_name="Jane Doe",
            address="456 Broadway",
            market_value=750_000,
            neighborhood="Tribeca",
        )
        assert "$750,000" in trigger

    def test_llc_trigger(self):
        trigger = _build_discovery_trigger(
            owner_name="Broadway Holdings Llc",
            address="789 Broadway",
            market_value=15_000_000,
            neighborhood="DUMBO",
        )
        assert "Broadway Holdings Llc" in trigger
        assert "$15.0M" in trigger


class TestZipToNeighborhood:
    """Test zip code to neighborhood mapping."""

    def test_tribeca_zip(self):
        assert _zip_to_neighborhood("10007") == "Tribeca"

    def test_west_village_zip(self):
        """10014 covers both Hudson Square and West Village."""
        assert _zip_to_neighborhood("10014") in ("West Village", "Hudson Square")

    def test_unknown_zip(self):
        assert _zip_to_neighborhood("99999") == "NYC"

    def test_williamsburg_zip(self):
        assert _zip_to_neighborhood("11211") == "Williamsburg"

    def test_queens_neighborhood(self):
        assert _zip_to_neighborhood("11357") == "Malba"

    def test_brooklyn_neighborhood(self):
        assert _zip_to_neighborhood("11222") == "Greenpoint"

    def test_hudson_yards_zip(self):
        assert _zip_to_neighborhood("10001") == "Hudson Yards"


class TestBuildAddress:
    """Test address cleanup from PLUTO records."""

    def test_full_address(self):
        result = _build_address({"address": "49 DOWNING STREET"})
        assert result == "49 Downing Street"

    def test_numbered_address(self):
        result = _build_address({"address": "114-03 198 STREET"})
        assert result == "114-03 198 Street"

    def test_empty_address(self):
        result = _build_address({"address": ""})
        assert result == "Unknown Address"

    def test_missing_field(self):
        result = _build_address({})
        assert result == "Unknown Address"


class TestLeadIntegration:
    """Test that the engine output integrates correctly with the Lead model."""

    def test_create_real_estate_lead(self):
        lead = Lead(
            first_name="John",
            last_name="Smith",
            address="123 W 10th St",
            city="New York",
            state="NY",
            zip_code="10014",
            estimated_wealth=8_200_000,
            discovery_trigger="John Smith owns $8.2M property at 123 W 10th St, West Village",
            source=LeadSource.TAX_ASSESSOR,
            confidence_score=0.7,
        )
        assert lead.source == LeadSource.TAX_ASSESSOR
        assert lead.full_name == "John Smith"
        assert lead.city == "New York"
        assert lead.state == "NY"

    def test_create_llc_lead(self):
        lead = Lead(
            first_name="",
            last_name="Broadway Holdings Llc",
            address="789 Broadway",
            city="New York",
            state="NY",
            zip_code="10013",
            company="Broadway Holdings Llc",
            estimated_wealth=15_000_000,
            discovery_trigger="Broadway Holdings Llc owns $15.0M property at 789 Broadway, Tribeca",
            source=LeadSource.TAX_ASSESSOR,
            confidence_score=0.45,
        )
        assert lead.source == LeadSource.TAX_ASSESSOR
        assert lead.company == "Broadway Holdings Llc"

    def test_neighborhood_presets_not_empty(self):
        """Sanity check: we have neighborhood data."""
        assert len(NEIGHBORHOOD_ZIP_CODES) >= 50, "Should have at least 50 neighborhoods"
        for name, zips in NEIGHBORHOOD_ZIP_CODES.items():
            assert len(zips) > 0, f"Neighborhood {name} has no zip codes"

    def test_all_boroughs_represented(self):
        """We should have neighborhoods in Manhattan, Brooklyn, and Queens."""
        all_zips = [z for zips in NEIGHBORHOOD_ZIP_CODES.values() for z in zips]
        has_manhattan = any(z.startswith("100") for z in all_zips)
        has_brooklyn = any(z.startswith("112") for z in all_zips)
        has_queens = any(z.startswith("11") and not z.startswith("112") for z in all_zips)
        assert has_manhattan
        assert has_brooklyn
        assert has_queens
