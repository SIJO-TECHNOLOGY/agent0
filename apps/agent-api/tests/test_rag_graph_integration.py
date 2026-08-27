"""Tests for the vector recall channel inside the graph (ADR-014)."""

from __future__ import annotations

import pytest

from app.graph.nodes import NodeContext, _augment_with_vector_recall
from app.mcp.mock_client import MockMcpClient
from app.models.intent import InterpretedIntent
from app.models.results import SearchResult
from app.rag.models import VectorHit
from app.services.search_strategy import classify_anchors


class FakeRagService:
    def __init__(self, hits: list[VectorHit]) -> None:
        self._hits = hits
        self.size = len(hits)
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs) -> list[VectorHit]:
        self.calls.append(kwargs)
        exclude = kwargs.get("exclude") or set()
        return [h for h in self._hits if h.candidate_id not in exclude]


def _intent(**constraints: str) -> InterpretedIntent:
    return InterpretedIntent(
        objective="trouver un developpeur java",
        entities=["java"],
        constraints=dict(constraints),
    )


def _anchors(intent: InterpretedIntent, *, name: str | None = None):
    return classify_anchors(
        intent.entities, intent.constraints, {"java"}, name=name
    )


def _ctx(rag: FakeRagService | None) -> NodeContext:
    return NodeContext(mcp_client=MockMcpClient(), rag_service=rag)


def _result(candidate_id: str) -> SearchResult:
    return SearchResult(
        id=candidate_id,
        type="consultant",
        title=f"candidate {candidate_id}",
        source_tool="searchCandidates",
    )


@pytest.mark.asyncio
async def test_vector_hits_are_appended_to_results() -> None:
    rag = FakeRagService(
        [VectorHit("100", 0.8, {"id": "100", "title": "Dev Java"})]
    )
    intent = _intent()
    results = [_result("1")]

    added = await _augment_with_vector_recall(
        _ctx(rag), intent=intent, anchors=_anchors(intent), results=results
    )

    assert added == 1
    assert [r.id for r in results] == ["1", "100"]
    appended = results[-1]
    assert appended.source_tool == "searchCandidates"
    assert appended.data["_rag_score"] == 0.8
    # Vector hits must EARN their rank in scoring, like any search summary.
    assert appended.score == 0.0


@pytest.mark.asyncio
async def test_candidates_already_found_are_not_duplicated() -> None:
    rag = FakeRagService([VectorHit("1", 0.9, {"id": "1"})])
    intent = _intent()
    results = [_result("1")]

    added = await _augment_with_vector_recall(
        _ctx(rag), intent=intent, anchors=_anchors(intent), results=results
    )

    assert added == 0
    assert len(results) == 1


@pytest.mark.asyncio
async def test_no_rag_service_means_no_change() -> None:
    intent = _intent()
    results = [_result("1")]

    added = await _augment_with_vector_recall(
        _ctx(None), intent=intent, anchors=_anchors(intent), results=results
    )

    assert added == 0
    assert len(results) == 1


@pytest.mark.asyncio
async def test_named_person_queries_skip_the_vector_channel() -> None:
    rag = FakeRagService([VectorHit("100", 0.9, {"id": "100"})])
    intent = _intent(name="Jean Dupont")
    results: list[SearchResult] = []

    added = await _augment_with_vector_recall(
        _ctx(rag),
        intent=intent,
        anchors=_anchors(intent, name="Jean Dupont"),
        results=results,
    )

    assert added == 0
    assert rag.calls == []


@pytest.mark.asyncio
async def test_a_failing_rag_service_degrades_to_keyword_only() -> None:
    class BrokenRag:
        size = 1

        async def search(self, **kwargs):
            raise RuntimeError("index down")

    intent = _intent()
    results = [_result("1")]

    added = await _augment_with_vector_recall(
        _ctx(BrokenRag()),  # type: ignore[arg-type]
        intent=intent,
        anchors=_anchors(intent),
        results=results,
    )

    assert added == 0
    assert len(results) == 1
