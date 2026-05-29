"""Unit tests for the SearchResult -> CandidateCard mapper."""

from __future__ import annotations

from app.models.results import SearchResult
from app.services.candidate_mapper import (
    candidate_card_from_result,
    candidate_cards_from_results,
    candidate_cards_with_diagnostics,
)


def _result(**overrides: object) -> SearchResult:
    base: dict[str, object] = {
        "id": "41924",
        "type": "candidate",
        "title": "",
        "snippet": "",
        "score": 1.0,
        "source_tool": "getCandidateDetail",
        "data": {},
    }
    base.update(overrides)
    return SearchResult.model_validate(base)


def test_full_name_built_from_first_and_last() -> None:
    card = candidate_card_from_result(
        _result(data={"firstName": "Sarah", "lastName": "Martin"})
    )
    assert card.full_name == "Sarah Martin"


def test_full_name_uses_single_available_part() -> None:
    only_first = candidate_card_from_result(_result(data={"firstName": "Sarah"}))
    only_last = candidate_card_from_result(_result(data={"lastName": "Martin"}))
    assert only_first.full_name == "Sarah"
    assert only_last.full_name == "Martin"


def test_full_name_is_none_when_no_name_fields_present() -> None:
    card = candidate_card_from_result(_result(data={}))
    assert card.full_name is None


def test_full_name_prefers_explicit_full_name_field() -> None:
    card = candidate_card_from_result(
        _result(
            data={
                "fullName": "Sarah M.",
                "firstName": "Sarah",
                "lastName": "Martin",
            }
        )
    )
    assert card.full_name == "Sarah M."


def test_unknown_scalar_fields_are_none_by_default() -> None:
    card = candidate_card_from_result(_result(data={}))
    assert card.title is None
    assert card.experience_years is None
    assert card.location is None
    assert card.availability is None


def test_skills_default_to_empty_list_when_missing() -> None:
    card = candidate_card_from_result(_result(data={}))
    assert card.skills == []


def test_skills_extracted_from_string_list() -> None:
    card = candidate_card_from_result(
        _result(data={"skills": ["Java", "Spring", "Kafka"]})
    )
    assert card.skills == ["Java", "Spring", "Kafka"]


def test_skills_extracted_from_object_list_with_name_field() -> None:
    card = candidate_card_from_result(
        _result(data={"skills": [{"name": "Java"}, {"label": "Spring"}]})
    )
    assert card.skills == ["Java", "Spring"]


def test_location_derived_from_city_and_country() -> None:
    card = candidate_card_from_result(
        _result(data={"city": "Paris", "country": "France"})
    )
    assert card.location == "Paris, France"


def test_location_falls_back_to_single_part() -> None:
    card = candidate_card_from_result(_result(data={"city": "Paris"}))
    assert card.location == "Paris"


def test_availability_label_used_when_present() -> None:
    card = candidate_card_from_result(
        _result(data={"availability": "Available immediately"})
    )
    assert card.availability == "Available immediately"


def test_availability_falls_back_to_date_field() -> None:
    card = candidate_card_from_result(
        _result(data={"availabilityDate": "2026-07-01"})
    )
    assert card.availability == "Available from 2026-07-01"


def test_experience_years_extracted_as_float() -> None:
    card = candidate_card_from_result(_result(data={"experienceYears": 7}))
    assert card.experience_years == 7.0


def test_match_score_is_none_for_detail_tools() -> None:
    card = candidate_card_from_result(
        _result(source_tool="getCandidateDetail", score=1.0)
    )
    assert card.match_score is None


def test_match_score_passes_through_for_search_tools() -> None:
    card = candidate_card_from_result(
        _result(source_tool="searchCandidates", score=0.86)
    )
    assert card.match_score == 0.86


def test_match_score_is_none_when_search_tool_score_is_zero() -> None:
    card = candidate_card_from_result(
        _result(source_tool="searchCandidates", score=0.0)
    )
    assert card.match_score is None


def test_boond_url_only_returned_for_http_strings() -> None:
    valid = candidate_card_from_result(
        _result(data={"boondUrl": "https://ui.boondmanager.com/candidates/41924"})
    )
    invalid = candidate_card_from_result(_result(data={"boondUrl": "not-a-url"}))
    empty = candidate_card_from_result(_result(data={}))
    assert valid.boond_url == "https://ui.boondmanager.com/candidates/41924"
    assert invalid.boond_url is None
    assert empty.boond_url is None


def test_summary_falls_back_to_generic_when_no_grounding_fields() -> None:
    card = candidate_card_from_result(_result(data={}))
    assert card.summary == "Candidate profile found in BoondManager."


def test_summary_uses_full_name_and_title_when_available() -> None:
    card = candidate_card_from_result(
        _result(data={"firstName": "Sarah", "jobTitle": "Java Engineer"})
    )
    assert "Sarah" in (card.summary or "")
    assert "Java Engineer" in (card.summary or "")


def test_title_fallback_to_id_is_not_surfaced_as_job_title() -> None:
    # `_record_to_result` falls back to the raw id when title is missing;
    # the mapper must not leak that fallback as a candidate job title.
    card = candidate_card_from_result(_result(title="41924"))
    assert card.title is None


def test_id_is_stringified() -> None:
    card = candidate_card_from_result(_result(id="41924"))
    assert isinstance(card.id, str)
    assert card.id == "41924"


def test_candidate_cards_from_results_preserves_order() -> None:
    a = _result(id="1")
    b = _result(id="2")
    c = _result(id="3")
    cards = candidate_cards_from_results([a, b, c])
    assert [card.id for card in cards] == ["1", "2", "3"]


def test_json_api_style_record_resolves_id_and_name() -> None:
    # MCP servers often return JSON:API-style: top-level id/type with
    # business fields under `attributes`. The mapper must read both.
    card = candidate_card_from_result(
        _result(
            id="41924",
            type="candidate",
            data={
                "attributes": {
                    "firstName": "Sarah",
                    "lastName": "Martin",
                    "city": "Paris",
                    "country": "France",
                    "jobTitle": "Senior Backend Engineer",
                    "skills": ["Java", "Spring"],
                }
            },
        )
    )
    assert card is not None
    assert card.id == "41924"
    assert card.full_name == "Sarah Martin"
    assert card.title == "Senior Backend Engineer"
    assert card.location == "Paris, France"
    assert card.skills == ["Java", "Spring"]


def test_card_dropped_when_record_has_no_resolvable_id() -> None:
    card = candidate_card_from_result(_result(id="", data={"firstName": "X"}))
    assert card is None


def test_card_filtered_out_in_batch_when_no_id() -> None:
    good = _result(id="1", data={"firstName": "Sarah"})
    bad = _result(id="", data={"firstName": "Anonymous"})
    cards = candidate_cards_from_results([good, bad])
    assert [card.id for card in cards] == ["1"]


def test_attributes_id_recovered_when_top_level_missing() -> None:
    card = candidate_card_from_result(
        _result(id="", data={"attributes": {"id": "9001", "firstName": "Maya"}})
    )
    assert card is not None
    assert card.id == "9001"
    assert card.full_name == "Maya"


def test_resolve_id_accepts_uuid_guid_and_candidate_id_aliases() -> None:
    for field_name, expected in (
        ("candidateId", "41924"),
        ("candidate_id", "41924"),
        ("uuid", "abcd-1234"),
        ("guid", "G-1"),
        ("key", "k-1"),
    ):
        card = candidate_card_from_result(
            _result(id="", data={field_name: expected, "firstName": "Sarah"})
        )
        assert card is not None, f"expected id from {field_name!r} to map"
        assert card.id == expected


def test_resolve_id_skips_placeholder_values() -> None:
    for placeholder in ("unknown", "null", "", None):
        card = candidate_card_from_result(
            _result(id="", data={"candidateId": placeholder, "firstName": "X"})
        )
        assert card is None


def test_candidate_cards_with_diagnostics_returns_drop_reasons() -> None:
    good = _result(id="1", data={"firstName": "Sarah"})
    bad = _result(id="", data={"firstName": "Anonymous", "city": "Lyon"})
    cards, dropped = candidate_cards_with_diagnostics([good, bad])
    assert [c.id for c in cards] == ["1"]
    assert len(dropped) == 1
    reason = dropped[0]
    assert reason["source_tool"] == bad.source_tool
    assert "no resolvable" in reason["reason"]
    # Safe: only the keys of the dropped record (no values) surface.
    assert "firstName" in reason["record_keys"]
    assert "Anonymous" not in repr(reason)


def test_internal_enrichment_keys_never_leak_through_skills_or_summary() -> None:
    card = candidate_card_from_result(
        _result(
            id="1",
            data={
                "firstName": "Sarah",
                "_enrichment_detail": {"firstName": "Should Not Surface"},
                "_enrichment_technical_document": {"text": "secret"},
            },
        )
    )
    assert card is not None
    assert card.full_name == "Sarah"
    serialized = card.model_dump_json()
    assert "_enrichment_detail" not in serialized
    assert "_enrichment_technical_document" not in serialized
    assert "secret" not in serialized
