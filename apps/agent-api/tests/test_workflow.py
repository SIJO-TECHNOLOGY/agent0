"""End-to-end LangGraph workflow tests with mocked MCP responses."""

from __future__ import annotations

import pytest

from app.graph.nodes import NodeContext
from app.graph.workflow import run_workflow
from app.mcp.client import McpToolError
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.tools import McpTool, ToolCallStatus


@pytest.mark.asyncio
async def test_workflow_happy_path_returns_results_and_summary() -> None:
    ctx = NodeContext(
        mcp_client=MockMcpClient(),
        max_replan_attempts=1,
        mcp_max_retries=1,
    )
    state = GraphState(
        original_query="Find senior Python consultants",
        filters={},
    )

    final = await run_workflow(state, ctx)

    assert final.interpreted_intent is not None
    assert final.execution_plan
    assert final.tool_calls
    assert final.results
    assert final.summary
    assert final.confidence > 0.0
    assert any(call.tool == "search_consultants" for call in final.tool_calls)


@pytest.mark.asyncio
async def test_workflow_replans_when_first_pass_empty() -> None:
    async def empty(_: dict[str, object]) -> list[dict[str, object]]:
        return []

    async def projects(_: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "id": "p-9",
                "type": "project",
                "title": "Replan result",
                "score": 0.8,
            }
        ]

    client = MockMcpClient(
        handlers={"search_consultants": empty, "search_projects": projects},
    )
    ctx = NodeContext(
        mcp_client=client,
        max_replan_attempts=1,
        mcp_max_retries=1,
    )
    state = GraphState(original_query="find consultants python")

    final = await run_workflow(state, ctx)

    assert final.replan_count == 1
    assert any(r.source_tool == "search_projects" for r in final.results)


@pytest.mark.asyncio
async def test_workflow_handles_tool_failure_safely() -> None:
    client = MockMcpClient(
        failures={
            "search_consultants": McpToolError(
                "validation error", tool="search_consultants"
            )
        }
    )
    ctx = NodeContext(
        mcp_client=client,
        max_replan_attempts=0,
        mcp_max_retries=1,
    )
    state = GraphState(original_query="find consultants python")

    final = await run_workflow(state, ctx)

    assert final.results == []
    assert any(call.status is ToolCallStatus.FAILED for call in final.tool_calls)
    assert any(w.code in {"tool_failed", "no_results"} for w in final.warnings)
    assert final.summary  # still produces a user-safe summary


@pytest.mark.asyncio
async def test_workflow_routes_candidate_id_query_to_get_candidate_detail() -> None:
    captured: dict[str, dict[str, object]] = {}

    async def get_candidate_detail(
        inputs: dict[str, object],
    ) -> list[dict[str, object]]:
        captured["inputs"] = dict(inputs)
        return [
            {
                "id": inputs.get("candidateId") or inputs.get("id"),
                "type": "candidate",
                "firstName": "Ada",
                "lastName": "Lovelace",
            }
        ]

    tool = McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
            "required": ["candidateId"],
        },
    )
    client = MockMcpClient(
        tools=[tool], handlers={"getCandidateDetail": get_candidate_detail}
    )
    ctx = NodeContext(
        mcp_client=client,
        max_replan_attempts=0,
        mcp_max_retries=1,
    )
    state = GraphState(
        original_query="Find the candidate information with candidate id 41924"
    )

    final = await run_workflow(state, ctx)

    assert captured == {"inputs": {"candidateId": 41924}}
    assert final.interpreted_intent is not None
    assert final.interpreted_intent.objective == "get_candidate_detail"
    assert any(call.tool == "getCandidateDetail" for call in final.tool_calls)
    assert any(
        call.inputs == {"candidateId": 41924}
        for call in final.tool_calls
        if call.tool == "getCandidateDetail"
    )
    assert final.results
    assert final.results[0].source_tool == "getCandidateDetail"
    assert final.results[0].id == "41924"
    assert final.summary


@pytest.mark.asyncio
async def test_workflow_warns_when_get_candidate_detail_not_available() -> None:
    # Default MockMcpClient does not expose getCandidateDetail.
    ctx = NodeContext(
        mcp_client=MockMcpClient(),
        max_replan_attempts=0,
        mcp_max_retries=1,
    )
    state = GraphState(original_query="candidate id 41924")

    final = await run_workflow(state, ctx)

    assert final.tool_calls == []
    assert final.results == []
    assert any(
        w.code == "tool_unavailable" and "getCandidateDetail" in w.message
        for w in final.warnings
    )


@pytest.mark.asyncio
async def test_workflow_does_not_exceed_replan_budget() -> None:
    async def empty(_: dict[str, object]) -> list[dict[str, object]]:
        return []

    client = MockMcpClient(
        handlers={
            "search_consultants": empty,
            "search_projects": empty,
            "search_opportunities": empty,
        }
    )
    ctx = NodeContext(
        mcp_client=client,
        max_replan_attempts=1,
        mcp_max_retries=1,
    )
    state = GraphState(original_query="find consultants python")

    final = await run_workflow(state, ctx)

    assert final.replan_count == 1
    assert final.results == []
    assert any(w.code == "no_results" for w in final.warnings)
