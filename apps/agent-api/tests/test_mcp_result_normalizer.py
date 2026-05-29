"""Unit tests for the shared MCP result normalizer."""

from __future__ import annotations

import pytest

from app.mcp.client import McpToolError
from app.mcp.result_normalizer import coerce_records


def test_unwraps_candidates_envelope_into_list_of_records() -> None:
    payload = {
        "candidates": [
            {"id": "41924", "firstName": "Sarah"},
            {"id": "41925", "firstName": "Alex"},
        ],
        "meta": {"currentPage": 1, "totalRows": 2},
    }
    out = coerce_records(payload, tool="searchCandidates")
    assert out == [
        {"id": "41924", "firstName": "Sarah"},
        {"id": "41925", "firstName": "Alex"},
    ]


def test_unwraps_legacy_results_items_and_data_keys() -> None:
    for key in ("results", "items", "data"):
        payload = {key: [{"id": "X"}], "meta": {"n": 1}}
        out = coerce_records(payload, tool="t")
        assert out == [{"id": "X"}], f"failed to unwrap key {key!r}"


def test_priority_order_results_wins_over_candidates() -> None:
    # Both keys present; the priority list places "results" first.
    payload = {
        "results": [{"id": "A"}],
        "candidates": [{"id": "B"}],
    }
    assert coerce_records(payload, tool="t") == [{"id": "A"}]


def test_does_not_unwrap_non_list_inner_value() -> None:
    payload = {"candidates": {"id": "X"}, "meta": {}}
    out = coerce_records(payload, tool="t")
    # Inner is a dict (not a list of dicts) — whole payload becomes a
    # single record, callers fall back to other id resolution paths.
    assert out == [payload]


def test_does_not_unwrap_list_of_non_dicts() -> None:
    payload = {"candidates": ["alice", "bob"], "meta": {}}
    out = coerce_records(payload, tool="t")
    # Inner is a list of strings — refuse to misread the envelope.
    assert out == [payload]


def test_list_input_is_validated_per_item_and_returned_as_dicts() -> None:
    raw = [{"id": "A"}, {"id": "B"}]
    out = coerce_records(raw, tool="t")
    assert out == raw
    # Each output dict is a fresh copy (not aliased).
    assert out[0] is not raw[0]


def test_list_input_with_non_dict_item_raises() -> None:
    with pytest.raises(McpToolError):
        coerce_records([{"id": "A"}, "not-a-dict"], tool="t")


def test_unsupported_top_level_type_raises() -> None:
    with pytest.raises(McpToolError):
        coerce_records("scalar", tool="t")


def test_envelope_with_no_known_wrapper_key_becomes_single_record() -> None:
    payload = {"id": "Z", "firstName": "Test"}
    assert coerce_records(payload, tool="t") == [payload]


def test_meta_alone_is_treated_as_single_record_not_dropped() -> None:
    # No wrapper key present: the dict (just meta) is returned as one
    # record — downstream mapper will likely drop it for lacking an id,
    # but the normalizer itself never silently swallows input.
    payload = {"meta": {"page": 1}}
    assert coerce_records(payload, tool="t") == [payload]
