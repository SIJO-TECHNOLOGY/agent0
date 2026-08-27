"""Tests for the in-memory vector index (ADR-014)."""

from __future__ import annotations

import math

from app.rag.index import VectorIndex
from app.rag.models import IndexedCandidate, normalise


def _entry(candidate_id: str, vector: list[float], **summary: object) -> IndexedCandidate:
    return IndexedCandidate(
        candidate_id=candidate_id,
        vector=normalise(vector),
        summary=summary or {"id": candidate_id},
    )


def test_empty_index_returns_no_hits() -> None:
    index = VectorIndex()

    assert index.size == 0
    assert index.search([1.0, 0.0]) == []


def test_search_orders_by_cosine_similarity() -> None:
    index = VectorIndex()
    index.rebuild(
        [
            _entry("exact", [1.0, 0.0]),
            _entry("orthogonal", [0.0, 1.0]),
            _entry("close", [0.9, 0.1]),
        ]
    )

    hits = index.search(normalise([1.0, 0.0]), top_k=3, min_score=0.0)

    assert [h.candidate_id for h in hits] == ["exact", "close", "orthogonal"]
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


def test_min_score_filters_weak_matches() -> None:
    index = VectorIndex()
    index.rebuild([_entry("exact", [1.0, 0.0]), _entry("orthogonal", [0.0, 1.0])])

    hits = index.search(normalise([1.0, 0.0]), top_k=10, min_score=0.5)

    assert [h.candidate_id for h in hits] == ["exact"]


def test_exclude_drops_already_found_candidates() -> None:
    index = VectorIndex()
    index.rebuild([_entry("a", [1.0, 0.0]), _entry("b", [0.95, 0.05])])

    hits = index.search(normalise([1.0, 0.0]), top_k=5, min_score=0.0, exclude={"a"})

    assert [h.candidate_id for h in hits] == ["b"]


def test_top_k_is_respected_after_exclusion() -> None:
    index = VectorIndex()
    index.rebuild([_entry(str(i), [1.0, i / 100]) for i in range(10)])

    hits = index.search(
        normalise([1.0, 0.0]), top_k=3, min_score=0.0, exclude={"0", "1"}
    )

    assert len(hits) == 3
    assert "0" not in {h.candidate_id for h in hits}
    assert "1" not in {h.candidate_id for h in hits}


def test_summary_travels_with_the_hit() -> None:
    index = VectorIndex()
    index.rebuild([_entry("42", [1.0, 0.0], id="42", title="Dev Java")])

    hits = index.search(normalise([1.0, 0.0]), min_score=0.0)

    assert hits[0].summary["title"] == "Dev Java"


def test_rebuild_drops_vectors_of_a_minority_dimension() -> None:
    index = VectorIndex()
    index.rebuild(
        [
            _entry("a", [1.0, 0.0, 0.0]),
            _entry("b", [0.0, 1.0, 0.0]),
            _entry("stale", [1.0, 0.0]),  # different dims — a model change
        ]
    )

    assert index.size == 2
    assert index.dims == 3
    assert "stale" not in index.indexed_ids()


def test_query_with_wrong_dimensions_returns_nothing() -> None:
    index = VectorIndex()
    index.rebuild([_entry("a", [1.0, 0.0, 0.0])])

    assert index.search([1.0, 0.0]) == []


def test_upsert_adds_new_and_replaces_existing() -> None:
    index = VectorIndex()
    index.rebuild([_entry("a", [1.0, 0.0])])

    index.upsert([_entry("b", [0.0, 1.0]), _entry("a", [0.0, 1.0], id="a", v="new")])

    assert index.size == 2
    hits = index.search(normalise([0.0, 1.0]), top_k=2, min_score=0.5)
    assert {h.candidate_id for h in hits} == {"a", "b"}
    updated = next(h for h in hits if h.candidate_id == "a")
    assert updated.summary["v"] == "new"


def test_rebuild_with_no_usable_entries_empties_the_index() -> None:
    index = VectorIndex()
    index.rebuild([_entry("a", [1.0, 0.0])])

    index.rebuild([IndexedCandidate(candidate_id="x", vector=[])])

    assert index.size == 0
    assert index.search([1.0, 0.0]) == []
