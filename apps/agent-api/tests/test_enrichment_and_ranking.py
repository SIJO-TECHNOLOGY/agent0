"""Tests for `enrich_candidates` and `rank_candidates` graph nodes."""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    ENRICHMENT_DETAIL_KEY,
    ENRICHMENT_TECH_DOC_KEY,
    NodeContext,
    enrich_candidates,
    rank_candidates,
)
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCallStatus


def _detail_tool() -> McpTool:
    return McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
        },
    )


def _tech_doc_tool() -> McpTool:
    return McpTool(
        name="getCandidateTechnicalDocument",
        description="Fetch the candidate's technical document.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
        },
    )


def _result(
    *, candidate_id: str, source_tool: str = "searchCandidates", data: dict | None = None
) -> SearchResult:
    return SearchResult(
        id=candidate_id,
        type="candidate",
        title="",
        score=0.5,
        source_tool=source_tool,
        data=dict(data or {}),
    )


def _ctx(client: MockMcpClient, *, max_enrichments: int = 5) -> NodeContext:
    return NodeContext(
        mcp_client=client,
        max_replan_attempts=0,
        mcp_max_retries=1,
        max_enrichments=max_enrichments,
    )


@pytest.mark.asyncio
async def test_enrich_calls_get_candidate_detail_for_top_n() -> None:
    captured: list[dict[str, object]] = []

    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        captured.append(dict(inputs))
        cid = inputs.get("candidateId") or inputs.get("id")
        return [{"id": cid, "firstName": f"First{cid}", "lastName": "Last"}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[_detail_tool()],
        results=[
            _result(candidate_id="1"),
            _result(candidate_id="2"),
            _result(candidate_id="3"),
        ],
    )

    result = await enrich_candidates(state, _ctx(client))

    assert sorted([c["candidateId"] for c in captured]) == [1, 2, 3]
    for enriched in result.results:
        assert ENRICHMENT_DETAIL_KEY in enriched.data
        assert "firstName" in enriched.data
    # All three detail calls recorded.
    detail_calls = [c for c in result.tool_calls if c.tool == "getCandidateDetail"]
    assert len(detail_calls) == 3
    assert all(c.status is ToolCallStatus.SUCCESS for c in detail_calls)


@pytest.mark.asyncio
async def test_enrich_respects_max_enrichments_limit() -> None:
    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": inputs.get("candidateId"), "firstName": "X"}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[_detail_tool()],
        results=[_result(candidate_id=str(i)) for i in range(10)],
    )

    result = await enrich_candidates(state, _ctx(client, max_enrichments=2))

    detail_calls = [c for c in result.tool_calls if c.tool == "getCandidateDetail"]
    assert len(detail_calls) == 2


@pytest.mark.asyncio
async def test_enrich_skips_results_from_non_search_tools() -> None:
    async def detail_handler(_inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": 42}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="candidate id 42",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail", constraints={"candidate_id": "42"}
        ),
        available_tools=[_detail_tool()],
        results=[_result(candidate_id="42", source_tool="getCandidateDetail")],
    )

    result = await enrich_candidates(state, _ctx(client))

    # No additional detail calls — the direct candidate-detail flow is
    # already authoritative and must not be re-fetched.
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_enrich_calls_technical_document_when_available_and_relevant() -> None:
    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": inputs.get("candidateId"), "firstName": "Sarah"}]

    async def doc_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "candidateId": inputs.get("candidateId"),
                "skills": ["Java", "Spring"],
                "text": "10 years backend experience on CIB platforms.",
            }
        ]

    client = MockMcpClient(
        tools=[_detail_tool(), _tech_doc_tool()],
        handlers={
            "getCandidateDetail": detail_handler,
            "getCandidateTechnicalDocument": doc_handler,
        },
    )

    state = GraphState(
        original_query="dev java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        available_tools=[_detail_tool(), _tech_doc_tool()],
        results=[_result(candidate_id="1")],
    )

    result = await enrich_candidates(state, _ctx(client))

    tools_called = [c.tool for c in result.tool_calls]
    assert "getCandidateDetail" in tools_called
    assert "getCandidateTechnicalDocument" in tools_called
    assert ENRICHMENT_TECH_DOC_KEY in result.results[0].data


@pytest.mark.asyncio
async def test_enrich_is_noop_when_detail_tool_missing() -> None:
    # No tools available means enrichment has nothing safe to do.
    client = MockMcpClient(tools=[])
    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[],
        results=[_result(candidate_id="1")],
    )

    result = await enrich_candidates(state, _ctx(client))

    assert result.tool_calls == []
    assert result.results == state.results


@pytest.mark.asyncio
async def test_rank_promotes_candidates_with_matching_evidence() -> None:
    state = GraphState(
        original_query="dev java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        results=[
            # Candidate with no evidence at all.
            _result(candidate_id="1", data={"firstName": "Alone"}),
            # Candidate whose tech doc mentions both Java and CIB.
            _result(
                candidate_id="2",
                data={
                    "firstName": "Sarah",
                    ENRICHMENT_TECH_DOC_KEY: {
                        "skills": ["Java"],
                        "text": "Long experience on CIB platforms",
                    },
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Evidence-rich candidate must end up first.
    assert result.results[0].id == "2"
    assert result.results[0].score > result.results[1].score


@pytest.mark.asyncio
async def test_rank_does_not_touch_non_search_results() -> None:
    state = GraphState(
        original_query="candidate id 42",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail", entities=["java"]
        ),
        results=[
            _result(
                candidate_id="42",
                source_tool="getCandidateDetail",
                data={"jobTitle": "Java Engineer"},
            )
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Score must be unchanged for non-search source tools.
    assert result.results[0].score == 0.5
