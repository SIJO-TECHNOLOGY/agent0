"""Unit tests for LLM planner prompt/context, parsing, and validation."""

from __future__ import annotations

import json

import pytest

from app.models.intent import LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool
from app.services.llm_planner import (
    LlmPlannerError,
    PlannerConstraints,
    StructuredLlmPlanner,
    build_planner_prompt,
    parse_plan_response,
    validate_plan,
)


def _search_candidates_tool() -> McpTool:
    return McpTool(
        name="searchCandidates",
        description="Search candidates by keyword string.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "string"},
                "page": {"type": "integer"},
                "numberPerPage": {"type": "integer"},
            },
        },
    )


def _detail_tool() -> McpTool:
    return McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
            "required": ["candidateId"],
        },
    )


def _tech_doc_tool() -> McpTool:
    return McpTool(
        name="getCandidateTechnicalDocument",
        description="Fetch the candidate's technical document.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
            "required": ["candidateId"],
        },
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_includes_query_tools_and_constraints() -> None:
    system, user = build_planner_prompt(
        query="search a java dev in CIB",
        filters={"region": "EU"},
        tools=[_search_candidates_tool(), _detail_tool()],
        constraints=PlannerConstraints(max_plan_steps=4, max_enrichments=3),
    )
    assert "MCP" in system
    assert "input_schema" in system
    # The planner must NOT be told to resolve dictionary ids (it plans in a
    # single pass and cannot), and must be told not to emit placeholders.
    assert "reuse its returned ids" not in system
    assert "<...>" in system
    assert "search a java dev in CIB" in user
    assert "region" in user
    assert "searchCandidates" in user
    assert "getCandidateDetail" in user
    assert '"max_plan_steps": 4' in user
    assert '"max_enrichments": 3' in user


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_plan_accepts_clean_json() -> None:
    payload = json.dumps(
        {
            "interpreted_intent": {"objective": "search"},
            "plan": [
                {
                    "tool_name": "searchCandidates",
                    "reason": "broad search",
                    "inputs": {"keywords": "java"},
                }
            ],
            "assumptions": [],
            "warnings": [],
        }
    )
    plan = parse_plan_response(payload)
    assert plan.plan[0].tool_name == "searchCandidates"


def test_parse_plan_tolerates_markdown_code_fence() -> None:
    payload = (
        "```json\n"
        + json.dumps(
            {
                "interpreted_intent": {},
                "plan": [
                    {
                        "tool_name": "getCandidateDetail",
                        "inputs": {"candidateId": 41924},
                    }
                ],
                "assumptions": [],
                "warnings": [],
            }
        )
        + "\n```"
    )
    plan = parse_plan_response(payload)
    assert plan.plan[0].inputs == {"candidateId": 41924}


def test_parse_plan_rejects_non_json() -> None:
    with pytest.raises(LlmPlannerError):
        parse_plan_response("Sorry, I can't comply right now.")


def test_parse_plan_rejects_top_level_array() -> None:
    with pytest.raises(LlmPlannerError):
        parse_plan_response("[]")


def test_parse_plan_rejects_unknown_top_level_keys() -> None:
    payload = json.dumps(
        {
            "interpreted_intent": {},
            "plan": [],
            "assumptions": [],
            "warnings": [],
            "rogue": "field",
        }
    )
    with pytest.raises(LlmPlannerError):
        parse_plan_response(payload)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _plan(*steps: PlannedToolCall) -> LlmToolPlan:
    return LlmToolPlan(plan=list(steps))


def test_validate_rejects_unknown_tool_name() -> None:
    plan = _plan(PlannedToolCall(tool_name="__nope__"))
    with pytest.raises(LlmPlannerError):
        validate_plan(plan, [_search_candidates_tool()], PlannerConstraints())


def test_validate_rejects_inputs_outside_schema() -> None:
    plan = _plan(
        PlannedToolCall(
            tool_name="searchCandidates",
            inputs={"keywords": "java", "secret": "leak"},
        )
    )
    with pytest.raises(LlmPlannerError):
        validate_plan(plan, [_search_candidates_tool()], PlannerConstraints())


def test_validate_rejects_missing_required_field_when_no_dependency() -> None:
    plan = _plan(PlannedToolCall(tool_name="getCandidateDetail", inputs={}))
    with pytest.raises(LlmPlannerError):
        validate_plan(plan, [_detail_tool()], PlannerConstraints())


def test_validate_allows_missing_required_when_dependency_will_fill_it() -> None:
    plan = _plan(
        PlannedToolCall(
            tool_name="searchCandidates", inputs={"keywords": "java"}
        ),
        PlannedToolCall(
            tool_name="getCandidateDetail",
            inputs={},
            depends_on="searchCandidates",
            result_selector="candidate_ids",
        ),
    )
    validated = validate_plan(
        plan,
        [_search_candidates_tool(), _detail_tool()],
        PlannerConstraints(),
    )
    assert [s.tool_name for s in validated.plan] == [
        "searchCandidates",
        "getCandidateDetail",
    ]


def test_validate_rejects_depends_on_referencing_unknown_prior_step() -> None:
    plan = _plan(
        PlannedToolCall(
            tool_name="getCandidateDetail",
            inputs={},
            depends_on="searchCandidates",
        )
    )
    with pytest.raises(LlmPlannerError):
        validate_plan(
            plan,
            [_search_candidates_tool(), _detail_tool()],
            PlannerConstraints(),
        )


def test_validate_drops_steps_with_unknown_result_selector() -> None:
    plan = _plan(
        PlannedToolCall(
            tool_name="searchCandidates", inputs={"keywords": "java"}
        ),
        PlannedToolCall(
            tool_name="getCandidateDetail",
            inputs={},
            depends_on="searchCandidates",
            result_selector="anything_else",
        ),
    )
    validated = validate_plan(
        plan,
        [_search_candidates_tool(), _detail_tool()],
        PlannerConstraints(),
    )
    # Only the valid step survives — bad steps are dropped rather than
    # failing the whole plan.
    assert [s.tool_name for s in validated.plan] == ["searchCandidates"]


def test_validate_truncates_to_max_plan_steps_and_keeps_only_valid() -> None:
    plan = _plan(
        PlannedToolCall(
            tool_name="searchCandidates", inputs={"keywords": "java"}
        ),
        PlannedToolCall(tool_name="__nope__"),
        PlannedToolCall(
            tool_name="getCandidateDetail",
            inputs={},
            depends_on="searchCandidates",
            result_selector="candidate_ids",
        ),
    )
    validated = validate_plan(
        plan,
        [_search_candidates_tool(), _detail_tool()],
        PlannerConstraints(max_plan_steps=2),
    )
    # Step 3 is dropped by truncation; step 2 is dropped by validation.
    assert [s.tool_name for s in validated.plan] == ["searchCandidates"]


def test_validate_raises_when_nothing_survives() -> None:
    plan = _plan(PlannedToolCall(tool_name="__nope__"))
    with pytest.raises(LlmPlannerError):
        validate_plan(plan, [_search_candidates_tool()], PlannerConstraints())


# ---------------------------------------------------------------------------
# StructuredLlmPlanner end-to-end (with stubbed ChatFn)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_planner_validates_against_discovered_tools() -> None:
    canned = {
        "interpreted_intent": {"objective": "candidate_search"},
        "plan": [
            {
                "tool_name": "searchCandidates",
                "inputs": {"keywords": "java cib", "page": 1},
            },
            {
                "tool_name": "getCandidateDetail",
                "inputs": {},
                "depends_on": "searchCandidates",
                "result_selector": "candidate_ids",
            },
        ],
        "assumptions": [],
        "warnings": [],
    }
    captured: dict[str, str] = {}

    async def chat_fn(system: str, user: str) -> str:
        captured["system"] = system
        captured["user"] = user
        return json.dumps(canned)

    planner = StructuredLlmPlanner(chat_fn=chat_fn)
    plan = await planner.plan(
        query="search a dev who knows java and CIB",
        filters={},
        tools=[_search_candidates_tool(), _detail_tool(), _tech_doc_tool()],
        constraints=PlannerConstraints(),
    )

    # Prompt actually carried the right context.
    assert "searchCandidates" in captured["user"]
    assert "getCandidateDetail" in captured["user"]
    # Plan was validated and returned in order.
    assert [step.tool_name for step in plan.plan] == [
        "searchCandidates",
        "getCandidateDetail",
    ]
