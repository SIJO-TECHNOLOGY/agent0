"""Unit tests for the conservative dictionary experience resolver."""

from __future__ import annotations

from app.services.dictionary_resolver import resolve_experience_id


def test_resolves_to_entry_with_n_plus_label() -> None:
    entries = [
        {"id": "exp-1", "label": "0-2 years"},
        {"id": "exp-2", "label": "2-5 years"},
        {"id": "exp-3", "label": "5-10 years"},
        {"id": "exp-4", "label": "10+ years"},
    ]
    # Only the "10+" entry has an open-ended threshold ≤ 10.
    assert resolve_experience_id(entries, min_years=10) == "exp-4"


def test_picks_highest_matching_threshold_when_multiple_open_ended() -> None:
    entries = [
        {"id": "exp-A", "label": "5+ years"},
        {"id": "exp-B", "label": "10+ years"},
        {"id": "exp-C", "label": "15+ years"},
    ]
    # min_years=12 → 5+ and 10+ both match; pick most-specific (10+).
    assert resolve_experience_id(entries, min_years=12) == "exp-B"


def test_returns_none_when_no_entry_has_numeric_threshold() -> None:
    entries = [
        {"id": "exp-1", "label": "Junior"},
        {"id": "exp-2", "label": "Senior"},
        {"id": "exp-3", "label": "Expert"},
    ]
    assert resolve_experience_id(entries, min_years=10) is None


def test_returns_none_when_thresholds_exceed_user_value() -> None:
    entries = [
        {"id": "exp-1", "label": "15+ years"},
        {"id": "exp-2", "label": "20+ years"},
    ]
    # 15+ is too restrictive for someone asking for 10 years.
    assert resolve_experience_id(entries, min_years=10) is None


def test_accepts_gte_and_and_more_label_variants() -> None:
    assert (
        resolve_experience_id(
            [{"id": "x", "label": "> 10 years"}], min_years=10
        )
        == "x"
    )
    assert (
        resolve_experience_id(
            [{"id": "x", "label": "10 years and more"}], min_years=12
        )
        == "x"
    )


def test_handles_json_api_style_entries_with_attributes() -> None:
    entries = [
        {
            "id": "exp-4",
            "type": "experience",
            "attributes": {"label": "10+ years"},
        }
    ]
    assert resolve_experience_id(entries, min_years=10) == "exp-4"


def test_skips_non_dict_entries_safely() -> None:
    entries = ["nope", 7, None, {"id": "ok", "label": "10+ years"}]
    assert resolve_experience_id(entries, min_years=10) == "ok"
