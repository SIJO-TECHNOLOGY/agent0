"""Unit tests for the conservative dictionary experience resolver."""

from __future__ import annotations

from app.services.dictionary_resolver import (
    dictionary_contract_entries,
    dictionary_section_entries,
    resolve_experience_id,
    resolve_tool_ids,
)


def test_dictionary_section_entries_extracts_nested_setting() -> None:
    raw = [
        {
            "setting": {
                "tool": [{"id": "t1", "label": "Java"}],
                "experience": [{"id": "e1", "label": "10+ years"}],
            }
        }
    ]
    assert dictionary_section_entries(raw, "tool") == [
        {"id": "t1", "label": "Java"}
    ]


def test_dictionary_section_entries_extracts_direct_shape() -> None:
    raw = [{"tool": [{"id": "t1", "label": "Java"}]}]
    assert dictionary_section_entries(raw, "tool") == [
        {"id": "t1", "label": "Java"}
    ]


def test_resolve_tool_ids_matches_case_insensitively_and_omits_misses() -> None:
    entries = [
        {"id": "java-id", "label": "Java"},
        {"id": "py-id", "label": "Python"},
    ]
    # "JAVA" matches Java; "cib" matches nothing -> omitted (never invented).
    assert resolve_tool_ids(entries, ["JAVA", "cib"]) == ["java-id"]


def test_resolve_tool_ids_returns_empty_when_no_match() -> None:
    entries = [{"id": "java-id", "label": "Java"}]
    assert resolve_tool_ids(entries, ["cib", "rust"]) == []


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


def test_dictionary_contract_entries_extracts_setting_variants() -> None:
    raw = [
        {"setting": {"typeOf": [{"id": -1, "label": "Non renseigné"}]}},
        {"setting": {"contract": [{"id": 2, "label": "CDI"}]}},
        {"setting": {"typeOf": {"contracts": [{"id": 3, "label": "Freelance"}]}}},
    ]

    assert dictionary_contract_entries(raw) == [
        {"id": -1, "label": "Non renseigné"},
        {"id": 2, "label": "CDI"},
        {"id": 3, "label": "Freelance"},
    ]


# ---------------------------------------------------------------------------
# Candidate pipeline states
# ---------------------------------------------------------------------------

_STATE_ENTRIES = [
    {"id": 0, "label": "Import à traiter"},
    {"id": 2, "label": "Qualifié"},
    {"id": 7, "label": "Vivier"},
    {"id": 8, "label": "A jouer"},
    {"id": 11, "label": "Ne plus contacter"},
    {"id": 12, "label": "A SUPPRIMER"},
]


def test_resolve_candidate_state_ids_is_accent_and_case_insensitive() -> None:
    from app.services.dictionary_resolver import resolve_candidate_state_ids

    matched, unresolved = resolve_candidate_state_ids(
        _STATE_ENTRIES, ["vivier", "QUALIFIE", "a jouer"]
    )
    assert matched == [2, 7, 8]
    assert unresolved == []


def test_resolve_candidate_state_ids_reports_unknown_labels() -> None:
    from app.services.dictionary_resolver import resolve_candidate_state_ids

    matched, unresolved = resolve_candidate_state_ids(
        _STATE_ENTRIES, ["Vivier", "Shortlist"]
    )
    assert matched == [7]
    assert unresolved == ["Shortlist"]


def test_detect_candidate_state_labels_multiword_and_cue() -> None:
    from app.services.dictionary_resolver import detect_candidate_state_labels

    # Multi-word label matches on its own; single-word label needs a cue.
    assert detect_candidate_state_labels(
        _STATE_ENTRIES, "je veux un dev C# a jouer"
    ) == ["A jouer"]
    assert detect_candidate_state_labels(
        _STATE_ENTRIES, "un dev C# en Vivier"
    ) == ["Vivier"]
    assert detect_candidate_state_labels(
        _STATE_ENTRIES, "candidats en qualifié"
    ) == ["Qualifié"]


def test_detect_candidate_state_labels_ignores_ordinary_vocabulary() -> None:
    from app.services.dictionary_resolver import detect_candidate_state_labels

    # "qualifié" without a state cue is ordinary vocabulary, not the state.
    assert detect_candidate_state_labels(
        _STATE_ENTRIES, "je cherche un dev très qualifié"
    ) == []
    assert detect_candidate_state_labels(_STATE_ENTRIES, "") == []


def test_candidate_state_options_excludes_forbidden_states() -> None:
    from app.services.dictionary_resolver import candidate_state_options

    raw = [{"setting": {"state": {"candidate": _STATE_ENTRIES}}}]
    options = candidate_state_options(raw)
    labels = [option["label"] for option in options]
    assert "Vivier" in labels and "A jouer" in labels
    assert "Ne plus contacter" not in labels
    assert "A SUPPRIMER" not in labels
