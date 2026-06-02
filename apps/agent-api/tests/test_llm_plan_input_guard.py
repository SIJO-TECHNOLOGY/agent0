"""Value-level input guarding + Agent-API-owned dictionary resolution.

Covers the corrective fix for the real-mode failure where the single-shot
LLM emitted placeholder ids (``"<JAVA_TOOL_ID>"``) that crashed the MCP
call. Execution must (1) never let placeholders/wrong types reach the
tool, and (2) resolve experience/tool dictionary ids itself.
"""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    NodeContext,
    _sanitize_tool_inputs,
    execute_llm_plan,
)
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool, ToolCall, ToolCallStatus
from app.services.search_service import _base_message


_SEARCH_TOOL = McpTool(
    name="searchCandidates",
    description="Search candidates.",
    input_schema={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "experiences": {"type": "array", "items": {"type": "integer"}},
            "tools": {"type": "array", "items": {"type": "string"}},
            "page": {"type": "integer"},
        },
    },
)

_DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Reference dictionary.",
    input_schema={"type": "object", "properties": {}},
)


def _ctx(client: MockMcpClient) -> NodeContext:
    return NodeContext(
        mcp_client=client, max_replan_attempts=0, mcp_max_retries=1
    )


# ---------------------------------------------------------------------------
# _sanitize_tool_inputs (unit)
# ---------------------------------------------------------------------------


def test_sanitize_drops_placeholder_scalar() -> None:
    schema = {"type": "object", "properties": {"keywords": {"type": "string"}}}
    clean, dropped = _sanitize_tool_inputs({"keywords": "<X>"}, schema)
    assert clean == {}
    assert dropped == ["keywords"]


def test_sanitize_drops_non_int_elements_from_int_array() -> None:
    clean, dropped = _sanitize_tool_inputs(
        {"experiences": ["<10PLUS_ID>"]}, _SEARCH_TOOL.input_schema
    )
    # The only element was a placeholder/non-int -> whole field dropped.
    assert "experiences" not in clean
    assert "experiences" in dropped


def test_sanitize_drops_operator_only_array() -> None:
    clean, dropped = _sanitize_tool_inputs(
        {"tools": ["#AND#", "<JAVA_ID>"]}, _SEARCH_TOOL.input_schema
    )
    # Placeholder stripped leaves only "#AND#" -> meaningless -> dropped.
    assert "tools" not in clean
    assert "tools" in dropped


def test_sanitize_keeps_valid_values() -> None:
    clean, dropped = _sanitize_tool_inputs(
        {
            "keywords": "java",
            "experiences": [5],
            "tools": ["java-id", "spring-id"],
            "page": 1,
        },
        _SEARCH_TOOL.input_schema,
    )
    assert dropped == []
    assert clean["keywords"] == "java"
    assert clean["experiences"] == [5]
    assert clean["tools"] == ["java-id", "spring-id"]
    assert clean["page"] == 1


# ---------------------------------------------------------------------------
# execute_llm_plan: guard prevents placeholders reaching the MCP call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_strips_placeholders_before_calling_search() -> None:
    captured: list[dict[str, object]] = []

    async def search_handler(inputs: dict[str, object]):
        captured.append(dict(inputs))
        return [{"id": 1, "attributes": {"jobTitle": "Java Engineer"}}]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL], handlers={"searchCandidates": search_handler}
    )
    # Sparse intent (no entities/constraints) -> the recall ladder is not
    # used, so this exercises the planned-input fallback path and its guard.
    state = GraphState(
        original_query="java 10 years cib",
        interpreted_intent=InterpretedIntent(objective="find"),
        available_tools=[_SEARCH_TOOL],
        llm_plan=LlmToolPlan(
            interpreted_intent={"objective": "find"},
            plan=[
                PlannedToolCall(
                    tool_name="searchCandidates",
                    inputs={
                        "keywords": "java",
                        "experiences": ["<10PLUS_EXPERIENCE_ID>"],
                        "tools": ["#AND#", "<JAVA_TOOL_ID>"],
                        "page": 1,
                    },
                )
            ],
        ),
    )

    result = await execute_llm_plan(state, _ctx(client))

    assert len(captured) == 1
    sent = captured[0]
    # No placeholder / wrongly-typed field ever reached the tool.
    assert "experiences" not in sent
    assert "tools" not in sent
    assert sent["keywords"] == "java"
    assert sent["page"] == 1
    # The search still ran and produced a candidate (no hard failure).
    assert result.results and result.results[0].id == "1"
    # Honest warning recorded.
    assert any(w.code == "filter_unresolved" for w in result.warnings)


# ---------------------------------------------------------------------------
# execute_llm_plan: Agent-API resolves dictionary ids from intent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planned_fallback_resolves_experience_filter_only() -> None:
    captured: list[dict[str, object]] = []

    async def search_handler(inputs: dict[str, object]):
        captured.append(dict(inputs))
        return [{"id": 1, "attributes": {"jobTitle": "Java Engineer"}}]

    async def dict_handler(_inputs: dict[str, object]):
        return [
            {
                "setting": {
                    "experience": [
                        {"id": 1, "label": "0-2 years"},
                        {"id": 5, "label": "10+ years"},
                    ],
                    "tool": [{"id": "java-id", "label": "Java"}],
                }
            }
        ]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        handlers={
            "searchCandidates": search_handler,
            "getDictionary": dict_handler,
        },
    )
    # Sparse intent (no anchors) -> the recall ladder is skipped and the
    # planned-input fallback runs, which injects the experience filter.
    state = GraphState(
        original_query="senior profile 10 years",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=[],
            constraints={"min_experience_years": "10"},
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        llm_plan=LlmToolPlan(
            interpreted_intent={"objective": "find"},
            plan=[
                PlannedToolCall(
                    tool_name="searchCandidates", inputs={"keywords": "java"}
                )
            ],
        ),
    )

    await execute_llm_plan(state, _ctx(client))

    sent = captured[0]
    # Experience resolved to the 10+ bucket id, coerced to an int array.
    assert sent["experiences"] == [5]
    assert sent["keywords"] == "java"
    # The unreliable structured `tools` filter is never injected.
    assert "tools" not in sent


# ---------------------------------------------------------------------------
# Honest message on a FAILED search tool
# ---------------------------------------------------------------------------


def test_failed_search_message_is_not_no_candidates() -> None:
    state = GraphState(
        original_query="java",
        tool_calls=[
            ToolCall(tool="searchCandidates", status=ToolCallStatus.FAILED)
        ],
    )
    message = _base_message([], state)
    assert "could not be completed" in message
    assert "No candidates matched" not in message
