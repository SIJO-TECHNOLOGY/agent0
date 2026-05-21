"""Unit tests for individual LangGraph nodes."""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    NodeContext,
    analyze_intent,
    build_plan,
    evaluate_results,
    execute_mcp_tools,
    generate_final_response,
    replan_if_needed,
    select_tools,
    should_replan,
)
from app.mcp.client import McpToolError
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, PlanStep
from app.models.tools import ToolCall, ToolCallStatus


def _ctx(client: MockMcpClient, *, max_replan: int = 1, retries: int = 2) -> NodeContext:
    return NodeContext(
        mcp_client=client,
        max_replan_attempts=max_replan,
        mcp_max_retries=retries,
    )


@pytest.mark.asyncio
async def test_analyze_intent_extracts_keywords_and_seniority() -> None:
    state = GraphState(original_query="Find senior Python developers")
    ctx = _ctx(MockMcpClient())

    result = await analyze_intent(state, ctx)

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.objective == "find_consultants"
    assert "python" in result.interpreted_intent.entities
    assert result.interpreted_intent.constraints.get("seniority") == "senior"


@pytest.mark.asyncio
async def test_analyze_intent_flags_empty_keywords() -> None:
    state = GraphState(original_query="find consultants")
    ctx = _ctx(MockMcpClient())

    result = await analyze_intent(state, ctx)

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.ambiguity_notes


@pytest.mark.asyncio
async def test_build_plan_produces_at_least_one_step() -> None:
    state = GraphState(
        original_query="consultants python",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["python"]
        ),
    )
    ctx = _ctx(MockMcpClient())

    result = await build_plan(state, ctx)

    assert result.execution_plan
    assert result.execution_plan[0].expected_tool == "search_consultants"
    assert result.execution_plan[0].inputs == {"keywords": ["python"]}


@pytest.mark.asyncio
async def test_build_plan_widens_after_replan() -> None:
    state = GraphState(
        original_query="consultants python",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["python"]
        ),
        replan_count=1,
    )
    ctx = _ctx(MockMcpClient())

    result = await build_plan(state, ctx)

    tools = [step.expected_tool for step in result.execution_plan]
    assert "search_consultants" in tools
    assert "search_projects" in tools
    assert "search_opportunities" in tools


@pytest.mark.asyncio
async def test_select_tools_warns_on_unavailable_tools() -> None:
    client = MockMcpClient(tools=[])  # no tools available
    state = GraphState(
        original_query="consultants",
        interpreted_intent=InterpretedIntent(objective="find_consultants"),
        execution_plan=[
            PlanStep(step=1, description="x", expected_tool="search_consultants")
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == []
    assert any(w.code == "tool_unavailable" for w in result.warnings)


@pytest.mark.asyncio
async def test_execute_mcp_tools_records_failed_call_without_raising() -> None:
    client = MockMcpClient(
        failures={"search_consultants": McpToolError("bad", tool="search_consultants")}
    )
    state = GraphState(
        original_query="consultants python",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["python"]
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="search_consultants",
                inputs={"keywords": ["python"]},
            )
        ],
        selected_tools=["search_consultants"],
    )

    result = await execute_mcp_tools(state, _ctx(client))

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status is ToolCallStatus.FAILED
    assert result.results == []
    assert any(w.code == "tool_failed" for w in result.warnings)


@pytest.mark.asyncio
async def test_execute_mcp_tools_retries_transient_failures() -> None:
    client = MockMcpClient(transient_failures={"search_consultants": 1})
    state = GraphState(
        original_query="consultants python",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["python"]
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="search_consultants",
                inputs={"keywords": ["python"]},
            )
        ],
        selected_tools=["search_consultants"],
    )

    result = await execute_mcp_tools(state, _ctx(client, retries=2))

    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.status is ToolCallStatus.SUCCESS
    assert call.attempts == 2
    assert result.results


@pytest.mark.asyncio
async def test_evaluate_results_marks_no_results_warning() -> None:
    state = GraphState(
        original_query="x",
        selected_tools=["search_consultants"],
        tool_calls=[
            ToolCall(
                tool="search_consultants",
                status=ToolCallStatus.EMPTY,
            )
        ],
    )

    result = await evaluate_results(state, _ctx(MockMcpClient()))

    assert result.confidence == 0.0
    assert any(w.code == "no_results" for w in result.warnings)


@pytest.mark.asyncio
async def test_replan_when_results_empty_and_budget_available() -> None:
    state = GraphState(
        original_query="x",
        selected_tools=["search_consultants"],
        execution_plan=[
            PlanStep(step=1, description="x", expected_tool="search_consultants")
        ],
        tool_calls=[
            ToolCall(tool="search_consultants", status=ToolCallStatus.EMPTY)
        ],
    )

    result = await replan_if_needed(state, _ctx(MockMcpClient(), max_replan=1))

    assert result.replan_count == 1
    assert result.execution_plan == []
    assert result.selected_tools == []
    assert should_replan(result) == "build_plan"


@pytest.mark.asyncio
async def test_no_replan_when_budget_exhausted() -> None:
    state = GraphState(
        original_query="x",
        selected_tools=["search_consultants"],
        execution_plan=[
            PlanStep(step=1, description="x", expected_tool="search_consultants")
        ],
        replan_count=1,
        tool_calls=[
            ToolCall(tool="search_consultants", status=ToolCallStatus.EMPTY)
        ],
    )

    result = await replan_if_needed(state, _ctx(MockMcpClient(), max_replan=1))

    assert result.replan_count == 1
    assert should_replan(result) == "generate_final_response"


@pytest.mark.asyncio
async def test_no_replan_when_results_present() -> None:
    state = GraphState(
        original_query="x",
        selected_tools=["search_consultants"],
        results=[],  # filled below via model_copy for clarity
    )
    # Inject a single result by rebuilding the state.
    from app.models.results import SearchResult

    state = state.model_copy(
        update={
            "results": [
                SearchResult(
                    id="1", type="consultant", title="t", source_tool="search_consultants"
                )
            ]
        }
    )
    result = await replan_if_needed(state, _ctx(MockMcpClient(), max_replan=1))
    assert result.replan_count == 0


@pytest.mark.asyncio
async def test_generate_final_response_ranks_and_summarizes() -> None:
    from app.models.results import SearchResult

    state = GraphState(
        original_query="x",
        results=[
            SearchResult(
                id="1",
                type="consultant",
                title="Low",
                score=0.2,
                source_tool="search_consultants",
            ),
            SearchResult(
                id="2",
                type="consultant",
                title="High",
                score=0.9,
                source_tool="search_consultants",
            ),
        ],
    )

    result = await generate_final_response(state, _ctx(MockMcpClient()))

    assert result.results[0].title == "High"
    assert "High" in result.summary
