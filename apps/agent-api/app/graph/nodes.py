"""LangGraph nodes for the Plan-and-Execute search workflow.

Each node is a small async function operating on the typed
`GraphState` model. Nodes return a new state instance (immutable
update) so the graph remains side-effect free.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.graph.intent_keywords import (
    detect_tools,
    extract_keywords,
    extract_seniority,
)
from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.models.errors import AgentError
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, PlanStep
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCall, ToolCallStatus
from app.models.warnings import Warning


@dataclass(frozen=True)
class NodeContext:
    """Dependencies passed to nodes by the workflow runner."""

    mcp_client: McpClient
    max_replan_attempts: int = 1
    mcp_max_retries: int = 2


def _replace(state: GraphState, **changes: object) -> GraphState:
    return state.model_copy(update=changes)


async def analyze_intent(state: GraphState, _: NodeContext) -> GraphState:
    """Interpret the natural-language query into structured intent."""
    query = state.original_query
    keywords = extract_keywords(query)
    seniority = extract_seniority(query)
    tool_hints = detect_tools(query)

    constraints: dict[str, str] = {}
    if seniority:
        constraints["seniority"] = seniority

    if "search_consultants" in tool_hints:
        objective = "find_consultants"
    elif "search_projects" in tool_hints:
        objective = "find_projects"
    elif "search_opportunities" in tool_hints:
        objective = "find_opportunities"
    else:
        objective = "search_consultants"

    ambiguity: list[str] = []
    if not keywords:
        ambiguity.append("Query did not contain explicit search keywords.")

    intent = InterpretedIntent(
        objective=objective,
        entities=keywords,
        constraints=constraints,
        ambiguity_notes=ambiguity,
    )
    return _replace(state, interpreted_intent=intent)


async def build_plan(state: GraphState, _: NodeContext) -> GraphState:
    """Produce a bounded execution plan."""
    intent = state.interpreted_intent
    if intent is None:
        return _replace(
            state,
            errors=[
                *state.errors,
                AgentError(
                    code="missing_intent",
                    message="Cannot build plan before intent analysis.",
                    node="build_plan",
                ),
            ],
        )

    tool_hints = detect_tools(state.original_query)
    if not tool_hints:
        tool_hints = ["search_consultants"]

    # A bounded replan widens the plan to adjacent tool surfaces.
    if state.replan_count > 0:
        for adjacent in ("search_projects", "search_opportunities"):
            if adjacent not in tool_hints:
                tool_hints.append(adjacent)

    inputs: dict[str, object] = {"keywords": list(intent.entities)}
    if "seniority" in intent.constraints:
        inputs["seniority"] = intent.constraints["seniority"]

    plan = [
        PlanStep(
            step=index + 1,
            description=f"Call {tool} with extracted keywords.",
            expected_tool=tool,
            inputs=dict(inputs),
        )
        for index, tool in enumerate(tool_hints)
    ]
    return _replace(state, execution_plan=plan)


async def select_tools(state: GraphState, ctx: NodeContext) -> GraphState:
    """Discover available MCP tools and resolve plan steps to real tools."""
    available: list[McpTool] = await ctx.mcp_client.discover_tools()
    available_names = {tool.name for tool in available}

    selected: list[str] = []
    warnings = list(state.warnings)
    for step in state.execution_plan:
        if not step.expected_tool:
            continue
        if step.expected_tool in available_names:
            if step.expected_tool not in selected:
                selected.append(step.expected_tool)
        else:
            warnings.append(
                Warning(
                    code="tool_unavailable",
                    message=(
                        f"Planned tool {step.expected_tool!r} is not available."
                    ),
                )
            )

    return _replace(
        state,
        available_tools=available,
        selected_tools=selected,
        warnings=warnings,
    )


async def _execute_single_tool(
    ctx: NodeContext,
    tool_name: str,
    inputs: dict[str, object],
) -> tuple[ToolCall, list[dict[str, object]]]:
    """Execute a tool with bounded retries on transient failures.

    Returns the sanitized tool call record and the raw result list
    (empty on failure).
    """
    attempt = 0
    start = time.perf_counter()
    last_error: Exception | None = None
    while attempt <= ctx.mcp_max_retries:
        attempt += 1
        try:
            raw = await ctx.mcp_client.call_tool(tool_name, inputs)
        except McpTransientError as exc:
            last_error = exc
            if attempt > ctx.mcp_max_retries:
                break
            continue
        except McpToolError as exc:
            latency = int((time.perf_counter() - start) * 1000)
            call = ToolCall(
                tool=tool_name,
                inputs=dict(inputs),
                status=ToolCallStatus.FAILED,
                latency_ms=latency,
                result_count=0,
                error_message=str(exc),
                attempts=attempt,
            )
            return call, []
        else:
            latency = int((time.perf_counter() - start) * 1000)
            status = ToolCallStatus.SUCCESS if raw else ToolCallStatus.EMPTY
            call = ToolCall(
                tool=tool_name,
                inputs=dict(inputs),
                status=status,
                latency_ms=latency,
                result_count=len(raw),
                attempts=attempt,
            )
            return call, list(raw)

    latency = int((time.perf_counter() - start) * 1000)
    call = ToolCall(
        tool=tool_name,
        inputs=dict(inputs),
        status=ToolCallStatus.FAILED,
        latency_ms=latency,
        result_count=0,
        error_message=(
            f"transient failure after {ctx.mcp_max_retries + 1} attempts: "
            f"{last_error}"
            if last_error
            else "transient failure"
        ),
        attempts=attempt,
    )
    return call, []


def _inputs_for_step(state: GraphState, tool_name: str) -> dict[str, object]:
    for step in state.execution_plan:
        if step.expected_tool == tool_name:
            return dict(step.inputs)
    return {}


def _record_to_result(record: dict[str, object], source_tool: str) -> SearchResult:
    raw_score = record.get("score", 0.0)
    try:
        score = float(raw_score) if raw_score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    well_known = {"id", "type", "title", "snippet", "score"}
    return SearchResult(
        id=str(record.get("id", "")),
        type=str(record.get("type", "unknown")),
        title=str(record.get("title", "")),
        snippet=str(record.get("snippet", "")),
        score=score,
        source_tool=source_tool,
        data={k: v for k, v in record.items() if k not in well_known},
    )


async def execute_mcp_tools(state: GraphState, ctx: NodeContext) -> GraphState:
    """Execute selected MCP tools and collect normalized results."""
    tool_calls = list(state.tool_calls)
    results = list(state.results)
    warnings = list(state.warnings)
    errors = list(state.errors)

    for tool_name in state.selected_tools:
        inputs = _inputs_for_step(state, tool_name)
        call, raw_records = await _execute_single_tool(ctx, tool_name, inputs)
        tool_calls.append(call)

        if call.status is ToolCallStatus.SUCCESS:
            for record in raw_records:
                if isinstance(record, dict):
                    results.append(_record_to_result(record, tool_name))
        elif call.status is ToolCallStatus.FAILED:
            warnings.append(
                Warning(
                    code="tool_failed",
                    message=(
                        f"Tool {tool_name!r} could not be executed reliably; "
                        "results may be incomplete."
                    ),
                )
            )
            errors.append(
                AgentError(
                    code="tool_call_failed",
                    message=call.error_message or "tool call failed",
                    node="execute_mcp_tools",
                    details={"tool": tool_name},
                )
            )

    # Deduplicate by (source_tool, id) preserving order.
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[SearchResult] = []
    for result in results:
        key = (result.source_tool, result.id)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(result)

    return _replace(
        state,
        tool_calls=tool_calls,
        results=deduped,
        warnings=warnings,
        errors=errors,
    )


async def evaluate_results(state: GraphState, _: NodeContext) -> GraphState:
    """Score result quality and confidence."""
    successful = [
        call for call in state.tool_calls if call.status is ToolCallStatus.SUCCESS
    ]
    failed = [
        call for call in state.tool_calls if call.status is ToolCallStatus.FAILED
    ]

    if not state.results:
        confidence = 0.0
    else:
        avg_score = sum(r.score for r in state.results) / len(state.results)
        coverage = min(1.0, len(successful) / max(1, len(state.selected_tools)))
        confidence = round(0.6 * avg_score + 0.4 * coverage, 3)

    warnings = list(state.warnings)
    if state.results and failed:
        warnings.append(
            Warning(
                code="partial_results",
                message="Some tools failed; results may be partial.",
            )
        )
    if not state.results and state.selected_tools:
        warnings.append(
            Warning(
                code="no_results",
                message="No matching results were found for your query.",
            )
        )

    return _replace(state, confidence=confidence, warnings=warnings)


async def replan_if_needed(state: GraphState, ctx: NodeContext) -> GraphState:
    """Bump replan counter when a bounded retry is warranted.

    Resets execution_plan and selected_tools so the next pass through
    `build_plan` produces a fresh, widened plan.
    """
    if state.results:
        return state
    if state.replan_count >= ctx.max_replan_attempts:
        return state
    if not state.selected_tools:
        # Nothing was actually executed; replanning won't change outcomes.
        return state

    # If every tool call hard-failed, replanning over the same surface is
    # unlikely to help. Only replan when the call layer worked but returned
    # empty results.
    only_failed = state.tool_calls and all(
        call.status is ToolCallStatus.FAILED for call in state.tool_calls
    )
    if only_failed:
        return state

    return _replace(
        state,
        replan_count=state.replan_count + 1,
        execution_plan=[],
        selected_tools=[],
    )


def should_replan(state: GraphState) -> str:
    """Conditional edge: route to build_plan when a replan is pending."""
    if not state.execution_plan and not state.selected_tools and state.replan_count > 0:
        return "build_plan"
    return "generate_final_response"


async def generate_final_response(state: GraphState, _: NodeContext) -> GraphState:
    """Rank results, produce a summary, and emit the final state."""
    ranked = sorted(state.results, key=lambda r: r.score, reverse=True)

    if ranked:
        top = ranked[0]
        summary = (
            f"Found {len(ranked)} result(s). Top match: {top.title} "
            f"(type={top.type}, score={top.score:.2f})."
        )
    else:
        summary = (
            "No results matched your query. Try refining keywords or removing "
            "filters."
        )

    return _replace(state, results=ranked, summary=summary)
