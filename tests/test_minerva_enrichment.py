"""Tests for the Minerva enrichment engine (all HTTP calls mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.engines.minerva_enrichment import (
    apply_cached_enrichment,
    build_enrich_record,
    enrich_people,
    record_id_for,
    summarize_result,
)

MATCH = {
    "record_id": "JANE_DOE|10021",
    "is_match": True,
    "minerva_pid": "p-abc",
    "match_score": 112.5,
    "phones": [
        {"phone_rank": 2, "phone_type": "Mobile", "phone_number": "2125550002"},
        {"phone_rank": 1, "phone_type": "Landline", "phone_number": "2125550001"},
    ],
    "personal_emails": [
        {"email_rank": 2, "email_address": "second@example.com"},
        {"email_rank": 1, "email_address": "jane@example.com"},
    ],
    "professional_emails": [{"email_rank": 1, "email_address": "jane@firm.com"}],
    "linkedin_url": "https://www.linkedin.com/in/janedoe",
}


class TestSummarizeResult:
    def test_prefers_mobile_phone_and_top_ranked_email(self) -> None:
        summary = summarize_result(MATCH)
        assert summary["phone"] == "2125550002"
        assert summary["phone_type"] == "Mobile"
        assert summary["email"] == "jane@example.com"
        assert summary["work_email"] == "jane@firm.com"
        assert summary["linkedin_url"] == "https://www.linkedin.com/in/janedoe"

    def test_falls_back_to_work_email(self) -> None:
        result = {**MATCH, "personal_emails": None}
        assert summarize_result(result)["email"] == "jane@firm.com"

    def test_no_match(self) -> None:
        assert summarize_result({"record_id": "x", "is_match": False}) == {"minerva_match": False}


class TestRecordIds:
    def test_record_id_ignores_middle_initial(self) -> None:
        row_a = {"owner_full_name": "Jane Q. Doe", "home_address": "1 EAST 70 STREET, 10021"}
        row_b = {"owner_full_name": "Jane Doe", "home_address": "1 EAST 70 STREET, 10021"}
        assert record_id_for(row_a) == record_id_for(row_b) == "JANE_DOE|10021"

    def test_build_record_uses_parsed_address(self) -> None:
        record = build_enrich_record("id1", "Jane Doe", "1 EAST 70 STREET", "10021")
        assert record == {"record_id": "id1", "full_name": "Jane Doe",
                          "address_line_1": "1 EAST 70 STREET", "zipcode": "10021"}

    def test_apply_cached_enrichment(self) -> None:
        rows = [
            {"owner_full_name": "Jane Doe", "home_address": "1 EAST 70 STREET, 10021"},
            {"owner_full_name": None, "home_address": "2 EAST 70 STREET, 10021"},
        ]
        cache = {"JANE_DOE|10021": summarize_result(MATCH)}
        assert apply_cached_enrichment(rows, cache) == 1
        assert rows[0]["phone"] == "2125550002"
        assert "phone" not in rows[1]

    def test_result_shared_across_same_persons_other_homes(self) -> None:
        rows = [{"owner_full_name": "Jane Doe", "home_address": "9 PARK PLACE, 11217"}]
        cache = {"JANE_DOE|10021": summarize_result(MATCH)}
        assert apply_cached_enrichment(rows, cache) == 1
        assert rows[0]["email"] == "jane@example.com"


    def test_match_wins_over_earlier_miss(self) -> None:
        rows = [{"owner_full_name": "Jane Doe", "home_address": "1 EAST 70 STREET, 10021"}]
        cache = {
            "JANE_DOE|10021": {"minerva_match": False},
            "JANE_DOE|10021|mail": summarize_result(MATCH),
        }
        apply_cached_enrichment(rows, cache)
        assert rows[0]["email"] == "jane@example.com"


class TestEnrichPeople:
    @pytest.fixture(autouse=True)
    def api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINERVA_API_KEY", "test-key")

    def test_cached_records_are_not_resent(self, tmp_path) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({"JANE_DOE|10021": {"minerva_match": False}}))
        records = [build_enrich_record("JANE_DOE|10021", "Jane Doe", "1 E 70 ST", "10021")]
        with patch("src.engines.minerva_enrichment.httpx.Client") as client_cls:
            result = enrich_people(records, str(cache_path))
        client_cls.return_value.__enter__.return_value.post.assert_not_called()
        assert result == {"JANE_DOE|10021": {"minerva_match": False}}

    def test_new_records_are_sent_and_cached(self, tmp_path) -> None:
        cache_path = tmp_path / "cache.json"
        records = [build_enrich_record("JANE_DOE|10021", "Jane Doe", "1 E 70 ST", "10021")]
        response = MagicMock(status_code=200)
        response.json.return_value = {"results": [MATCH]}
        with patch("src.engines.minerva_enrichment.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.return_value = response
            result = enrich_people(records, str(cache_path))
        assert client.post.call_args.kwargs["json"]["records"] == records
        assert result["JANE_DOE|10021"]["email"] == "jane@example.com"
        assert json.loads(cache_path.read_text())["JANE_DOE|10021"]["minerva_match"] is True

    def test_stops_when_allowance_runs_out(self, tmp_path) -> None:
        records = [build_enrich_record("JANE_DOE|10021", "Jane Doe", "1 E 70 ST", "10021")]
        response = MagicMock(status_code=402, text="insufficient_record_capacity")
        with patch("src.engines.minerva_enrichment.httpx.Client") as client_cls:
            client_cls.return_value.__enter__.return_value.post.return_value = response
            result = enrich_people(records, str(tmp_path / "cache.json"))
        assert result == {}
