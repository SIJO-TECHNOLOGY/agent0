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
from app.models.tools import McpTool, ToolCall, ToolCallStatus


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
async def test_analyze_intent_detects_candidate_detail_lookup() -> None:
    state = GraphState(
        original_query="Find the candidate information with candidate id 41924"
    )
    ctx = _ctx(MockMcpClient())

    result = await analyze_intent(state, ctx)

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.objective == "get_candidate_detail"
    assert result.interpreted_intent.constraints.get("candidate_id") == "41924"
    # Candidate-id lookups do not need keyword ambiguity warnings.
    assert result.interpreted_intent.ambiguity_notes == []


@pytest.mark.asyncio
async def test_analyze_intent_tolerates_candidate_id_typo() -> None:
    state = GraphState(original_query="cadidate id 41924")
    ctx = _ctx(MockMcpClient())

    result = await analyze_intent(state, ctx)

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.objective == "get_candidate_detail"
    assert result.interpreted_intent.constraints.get("candidate_id") == "41924"


@pytest.mark.asyncio
async def test_build_plan_produces_get_candidate_detail_step() -> None:
    state = GraphState(
        original_query="candidate id 41924",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail",
            constraints={"candidate_id": "41924"},
        ),
    )
    ctx = _ctx(MockMcpClient())

    result = await build_plan(state, ctx)

    assert len(result.execution_plan) == 1
    step = result.execution_plan[0]
    assert step.expected_tool == "getCandidateDetail"
    # Planner uses candidateId as a placeholder; select_tools may rewrite.
    assert step.inputs == {"candidateId": 41924}


@pytest.mark.asyncio
async def test_select_tools_rewrites_inputs_when_schema_uses_id_field() -> None:
    tool = McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    )
    client = MockMcpClient(tools=[tool])
    state = GraphState(
        original_query="candidate id 41924",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail",
            constraints={"candidate_id": "41924"},
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="getCandidateDetail",
                inputs={"candidateId": 41924},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == ["getCandidateDetail"]
    assert result.execution_plan[0].inputs == {"id": 41924}


@pytest.mark.asyncio
async def test_select_tools_preserves_candidate_id_inputs_when_schema_matches() -> None:
    tool = McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by candidateId.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
            "required": ["candidateId"],
        },
    )
    client = MockMcpClient(tools=[tool])
    state = GraphState(
        original_query="candidate id 41924",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail",
            constraints={"candidate_id": "41924"},
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="getCandidateDetail",
                inputs={"candidateId": 41924},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == ["getCandidateDetail"]
    assert result.execution_plan[0].inputs == {"candidateId": 41924}


@pytest.mark.asyncio
async def test_select_tools_picks_search_candidates_over_legacy_mock() -> None:
    real_tool = McpTool(
        name="searchCandidates",
        description="Search candidates.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "string"},
                "page": {"type": "integer"},
                "numberPerPage": {"type": "integer"},
            },
        },
    )
    # Mock client exposes ONLY the real tool, not the legacy one — so the
    # fallback path is exercised even though both names are listed.
    client = MockMcpClient(tools=[real_tool])
    state = GraphState(
        original_query="dev java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="searchCandidates",
                alternative_tools=["search_consultants"],
                inputs={"keywords": ["java", "cib"]},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == ["searchCandidates"]
    step = result.execution_plan[0]
    assert step.expected_tool == "searchCandidates"
    assert step.alternative_tools == []
    # keywords must be a string, page/numberPerPage defaults injected.
    assert step.inputs == {
        "keywords": "java cib",
        "page": 1,
        "numberPerPage": 10,
    }


@pytest.mark.asyncio
async def test_select_tools_falls_back_to_legacy_when_real_tool_missing() -> None:
    # Default MockMcpClient exposes search_consultants but not searchCandidates.
    client = MockMcpClient()
    state = GraphState(
        original_query="java consultants",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="searchCandidates",
                alternative_tools=["search_consultants"],
                inputs={"keywords": ["java"]},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == ["search_consultants"]
    step = result.execution_plan[0]
    assert step.expected_tool == "search_consultants"
    # Legacy tool keeps its list-shaped keywords (no schema rewrite for it).
    assert step.inputs == {"keywords": ["java"]}


@pytest.mark.asyncio
async def test_select_tools_emits_unmapped_experience_warning() -> None:
    real_tool = McpTool(
        name="searchCandidates",
        description="Search candidates.",
        input_schema={
            "type": "object",
            "properties": {"keywords": {"type": "string"}},
        },
    )
    client = MockMcpClient(tools=[real_tool])
    state = GraphState(
        original_query="dev java 10 years experience",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants",
            entities=["java"],
            constraints={"min_experience_years": "10"},
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="searchCandidates",
                alternative_tools=["search_consultants"],
                inputs={"keywords": ["java"]},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert any(
        w.code == "experience_filter_unmapped" for w in result.warnings
    )
    # We still proceeded with the search rather than inventing a filter id.
    assert result.selected_tools == ["searchCandidates"]
    assert result.execution_plan[0].inputs == {"keywords": "java"}


@pytest.mark.asyncio
async def test_select_tools_warns_when_get_candidate_detail_unavailable() -> None:
    # Default MockMcpClient does not expose getCandidateDetail.
    client = MockMcpClient()
    state = GraphState(
        original_query="candidate id 41924",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail",
            constraints={"candidate_id": "41924"},
        ),
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="getCandidateDetail",
                inputs={"candidateId": 41924},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == []
    assert any(
        w.code == "tool_unavailable" and "getCandidateDetail" in w.message
        for w in result.warnings
    )


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
    # Real MCP tool is preferred; legacy mock tool stays as fallback so
    # mock-mode discovery still resolves to a valid tool.
    assert result.execution_plan[0].expected_tool == "searchCandidates"
    assert "search_consultants" in result.execution_plan[0].alternative_tools
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

    expected_tools = [step.expected_tool for step in result.execution_plan]
    fallback_tools = [
        name for step in result.execution_plan for name in step.alternative_tools
    ]
    assert "searchCandidates" in expected_tools
    assert "search_consultants" in fallback_tools
    assert "search_projects" in expected_tools
    assert "search_opportunities" in expected_tools


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
async def test_select_tools_resolves_real_mcp_candidate_tool_alias() -> None:
    client = MockMcpClient(
        tools=[
            McpTool(
                name="searchCandidates",
                description="Search candidates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string"},
                        "page": {"type": "integer"},
                        "numberPerPage": {"type": "integer"},
                    },
                },
            )
        ]
    )
    state = GraphState(
        original_query="consultants java",
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="searchCandidates",
                inputs={"keywords": ["java"]},
            )
        ],
    )

    result = await select_tools(state, _ctx(client))

    assert result.selected_tools == ["searchCandidates"]


@pytest.mark.asyncio
async def test_execute_mcp_tools_adapts_candidate_tool_inputs_and_output() -> None:
    async def search_candidates(inputs: dict[str, object]) -> list[dict[str, object]]:
        assert inputs["keywords"] == "java senior"
        return [
            {
                "id": 42,
                "firstName": "Ada",
                "lastName": "Lovelace",
                "city": "Paris",
                "technicalDocument": {
                    "title": "Backend Java Engineer",
                    "skills": "Java, Spring",
                },
            }
        ]

    client = MockMcpClient(
        tools=[McpTool(name="searchCandidates", description="", input_schema={})],
        handlers={"searchCandidates": search_candidates},
    )
    state = GraphState(
        original_query="consultants java senior",
        execution_plan=[
            PlanStep(
                step=1,
                description="x",
                expected_tool="searchCandidates",
                inputs={"keywords": "java senior"},
            )
        ],
        selected_tools=["searchCandidates"],
    )

    result = await execute_mcp_tools(state, _ctx(client))

    assert result.tool_calls[0].tool == "searchCandidates"
    assert result.results[0].id == "42"
    assert result.results[0].title == "Backend Java Engineer"
    assert result.results[0].snippet == "Java, Spring"


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
    # When the replan budget is exhausted, the workflow now proceeds
    # through enrichment + ranking before generating the final response.
    assert should_replan(result) == "enrich_candidates"


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
