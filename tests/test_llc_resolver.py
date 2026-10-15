"""Tests for the LLC/trust resolver's matching and ranking logic (no API calls)."""

from src.engines.llc_resolver import (
    OwnerCandidate,
    _add_person_portfolios,
    _bbl_parts,
    _candidate_belongs_to_entity,
    classify_owner,
    clean_person_name,
    llc_names_match,
    normalize_llc_name,
    person_key,
    pick_best_owner,
)


class TestLlcNameMatching:
    def test_normalize_strips_suffix_and_punctuation(self) -> None:
        assert normalize_llc_name("High Castle Realty, L.L.C.") == "HIGH CASTLE REALTY"

    def test_variants_match(self) -> None:
        assert llc_names_match("37 CHARLTON SA LLC", "37 Charlton SA, LLC")

    def test_different_llcs_do_not_match(self) -> None:
        assert not llc_names_match("37 CHARLTON SA LLC", "41 CHARLTON SA LLC")
        assert not llc_names_match("ELDRIDGE HOUSE LLC", "TRINITY REAL ESTATE")

    def test_placeholders_do_not_match(self) -> None:
        assert not llc_names_match("N/A", "ACME LLC")
        assert not llc_names_match(None, "ACME LLC")


class TestPersonNames:
    def test_clean_person_name_title_cases(self) -> None:
        assert clean_person_name("JASON", "BECKMAN") == "Jason Beckman"

    def test_rejects_placeholders_and_companies(self) -> None:
        assert clean_person_name("N/A") is None
        assert clean_person_name("ACME", "MANAGEMENT LLC") is None
        assert clean_person_name("MADONNA") is None

    def test_person_key_ignores_middle_initial(self) -> None:
        assert person_key("Jason R. Beckman") == person_key("Jason Beckman")


class TestBblParts:
    def test_splits_pluto_bbl(self) -> None:
        assert _bbl_parts("1000970044.00000000") == ("1", "97", "44")


class TestResolution:
    def test_candidate_must_act_for_same_llc(self) -> None:
        own = OwnerCandidate("Jason Beckman", "DOB NOW permit", on_behalf_of="37 CHARLTON SA LLC")
        prior = OwnerCandidate("Karen Rechtel", "DOB permit (legacy)", on_behalf_of="N/A")
        assert _candidate_belongs_to_entity(own, "37 CHARLTON SA, LLC")
        assert not _candidate_belongs_to_entity(prior, "37 CHARLTON SA, LLC")

    def test_family_surname_confirms_trust_permit(self) -> None:
        relative = OwnerCandidate("Jane Toth", "DOB NOW permit", on_behalf_of="N/A")
        stranger = OwnerCandidate("Karen Rechtel", "DOB NOW permit", on_behalf_of="N/A")
        assert _candidate_belongs_to_entity(relative, "TOTH FAMILY TRUST", family_surname="Toth")
        assert not _candidate_belongs_to_entity(stranger, "TOTH FAMILY TRUST", family_surname="Toth")

    def test_trust_dates_do_not_block_name_match(self) -> None:
        assert llc_names_match("GREG POLLACK LIVING TRUST", "GREG POLLACK LIVING TRUST, DATED MAY 3, 2013")

    def test_more_sources_wins(self) -> None:
        candidates = [
            OwnerCandidate("Ann Lee", "DOB NOW permit", record_date="2025-01-01"),
            OwnerCandidate("Bob Stone", "DOB NOW permit", record_date="2020-01-01"),
            OwnerCandidate("Bob Stone", "HPD registration", role="MEMBER"),
        ]
        best = pick_best_owner(candidates)
        assert best["full_name"] == "Bob Stone"
        assert best["confidence"] == "High"
        assert best["other_people"] == ["Ann Lee"]

    def test_recency_breaks_ties(self) -> None:
        candidates = [
            OwnerCandidate("Ann Lee", "DOB NOW permit", record_date="2025-01-01"),
            OwnerCandidate("Bob Stone", "DOB NOW permit", record_date="2020-01-01"),
        ]
        assert pick_best_owner(candidates)["full_name"] == "Ann Lee"

    def test_trust_named_person_beats_relative(self) -> None:
        candidates = [
            OwnerCandidate("Filippo Pennino", "DOB permit (legacy)", record_date="2021-01-01"),
            OwnerCandidate("Giorgio Pennino", "Trust name"),
        ]
        best = pick_best_owner(candidates)
        assert best["full_name"] == "Giorgio Pennino"
        assert best["other_people"] == ["Filippo Pennino"]

    def test_no_candidates(self) -> None:
        assert pick_best_owner([]) is None

    def test_person_portfolio_sums_across_llcs(self) -> None:
        rows = [
            {"owner_full_name": "Bob Stone", "entity_portfolio_value": 5_000_000,
             "entity_portfolio_properties": 1, "confidence": "High"},
            {"owner_full_name": "Bob J Stone", "entity_portfolio_value": 3_000_000,
             "entity_portfolio_properties": 1, "confidence": "Medium"},
            {"owner_full_name": None, "entity_portfolio_value": 9_000_000,
             "entity_portfolio_properties": 1, "confidence": "Unresolved"},
        ]
        result = _add_person_portfolios(rows)
        assert result[0]["person_total_value"] == 8_000_000
        assert result[0]["person_entity_count"] == 2
        assert result[-1]["person_total_value"] == 9_000_000

    def test_classify_owner(self) -> None:
        assert classify_owner(1, 1) == "Private homeowner"
        assert classify_owner(2, 1) == "Investor"
        assert classify_owner(1, 38) == "Investor"
        assert classify_owner(12, 1) == "Likely manager / agent"
