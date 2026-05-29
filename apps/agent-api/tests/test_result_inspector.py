"""Unit tests for the sanitized result-inspection helpers."""

from __future__ import annotations

from app.services.result_inspector import (
    sanitized_preview,
    summarize_result_shape,
)


def test_summarize_returns_zero_counts_for_empty_input() -> None:
    summary = summarize_result_shape([])
    assert summary["record_count"] == 0
    assert summary["top_level_keys"] == []
    assert summary["nested_keys"] == {}


def test_summarize_top_level_and_nested_keys_only_no_values() -> None:
    records = [
        {
            "id": "X",
            "attributes": {
                "firstName": "Sarah",
                "city": "Paris",
            },
            "relationships": {"manager": {"id": "Y"}},
        }
    ]
    summary = summarize_result_shape(records)
    assert summary["record_count"] == 1
    assert summary["top_level_keys"] == ["attributes", "id", "relationships"]
    assert "attributes" in summary["nested_keys"]
    assert "firstName" in summary["nested_keys"]["attributes"]
    # No values leak into the shape summary.
    text = repr(summary)
    assert "Sarah" not in text
    assert "Paris" not in text


def test_summarize_handles_lists_of_dicts_in_nested_keys() -> None:
    records = [{"skills": [{"name": "Java"}, {"name": "Spring"}]}]
    summary = summarize_result_shape(records)
    assert "skills[0]" in summary["nested_keys"]
    assert summary["nested_keys"]["skills[0]"] == ["name"]


def test_sanitized_preview_truncates_long_strings_and_caps_records() -> None:
    long_text = "a" * 5000
    records = [{"text": long_text}] * 10
    preview = sanitized_preview(records)
    # Default cap is 2 records.
    assert len(preview) <= 2
    rendered = preview[0]
    assert isinstance(rendered, dict)
    truncated = rendered["text"]
    assert isinstance(truncated, str)
    assert truncated.endswith("...(truncated)")
    assert len(truncated) < len(long_text)


def test_sanitized_preview_redacts_known_sensitive_keys() -> None:
    records = [
        {
            "api_key": "sk-real-secret",
            "token": "abc",
            "Authorization": "Bearer xyz",
            "cv_text": "very long resume body",
            "firstName": "Sarah",
        }
    ]
    preview = sanitized_preview(records)
    assert preview[0]["api_key"] == "...(redacted)"
    assert preview[0]["token"] == "...(redacted)"
    assert preview[0]["Authorization"] == "...(redacted)"
    assert preview[0]["cv_text"] == "...(redacted)"
    # Non-sensitive fields stay visible.
    assert preview[0]["firstName"] == "Sarah"


def test_sanitized_preview_caps_recursion_depth() -> None:
    deeply: dict[str, object] = {"v": 0}
    cursor = deeply
    for _ in range(10):
        cursor["child"] = {"v": 0}
        cursor = cursor["child"]  # type: ignore[assignment]
    rendered = sanitized_preview([deeply])[0]
    # Walk down and confirm the depth guard fires.
    text = repr(rendered)
    assert "depth-truncated" in text


def test_sanitized_preview_caps_list_length() -> None:
    records = [{"skills": list(range(100))}]
    rendered = sanitized_preview(records)[0]
    assert isinstance(rendered["skills"], list)
    assert len(rendered["skills"]) <= 10
