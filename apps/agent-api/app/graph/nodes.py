"""LangGraph nodes for the Plan-and-Execute search workflow.

Each node is a small async function operating on the typed
`GraphState` model. Nodes return a new state instance (immutable
update) so the graph remains side-effect free.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Final

logger = logging.getLogger(__name__)

from app.graph.intent_keywords import (
    detect_tools,
    extract_candidate_id,
    extract_keywords,
    extract_min_years_experience,
    extract_seniority,
)
from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.models.errors import AgentError
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, PlanStep
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCall, ToolCallStatus
from app.services.candidate_mapper import (
    candidate_cards_from_results,
    candidate_cards_with_diagnostics,
)
from app.services.dictionary_resolver import resolve_experience_id
from app.services.event_emitter import EventEmitter, NoopEventEmitter
from app.services.result_inspector import (
    sanitized_preview,
    summarize_result_shape,
)
from app.services.llm_planner import (
    LlmPlanner,
    LlmPlannerError,
    PlannerConstraints,
)
from app.models.warnings import Warning


DEFAULT_ENRICHMENT_LIMIT: Final[int] = 5
DEFAULT_LLM_PLAN_STEPS: Final[int] = 6


@dataclass(frozen=True)
class NodeContext:
    """Dependencies passed to nodes by the workflow runner."""

    mcp_client: McpClient
    max_replan_attempts: int = 1
    mcp_max_retries: int = 2
    max_enrichments: int = DEFAULT_ENRICHMENT_LIMIT
    llm_planner: LlmPlanner | None = None
    max_plan_steps: int = DEFAULT_LLM_PLAN_STEPS
    event_emitter: EventEmitter = field(default_factory=NoopEventEmitter)
    debug_mode: bool = False


def _replace(state: GraphState, **changes: object) -> GraphState:
    return state.model_copy(update=changes)


def _serialize_tool_entry(tool: McpTool) -> dict[str, object]:
    """Sanitized view of a discovered MCP tool for the tools_discovered event.

    Surfaces only the tool name and the *keys* of its input schema —
    never the full schema body — so we don't leak provider-specific
    descriptions or vendor metadata to the frontend.
    """
    properties: object = {}
    if isinstance(tool.input_schema, dict):
        properties = tool.input_schema.get("properties", {})
    keys: list[str] = (
        sorted(str(k) for k in properties.keys())
        if isinstance(properties, dict)
        else []
    )
    return {"name": tool.name, "input_schema_keys": keys}


def _serialize_plan_step_event(step: PlanStep) -> dict[str, object]:
    """Sanitized view of a deterministic-mode PlanStep for plan_created."""
    return {
        "step": step.step,
        "tool_name": step.expected_tool,
        "reason": step.description,
        "inputs": dict(step.inputs),
        "depends_on": None,
        "result_selector": None,
    }


def _candidate_ids_in(results: list[SearchResult], source_tool: str) -> list[str]:
    """Return de-duplicated candidate ids produced by ``source_tool``."""
    seen: set[str] = set()
    ordered: list[str] = []
    for result in results:
        if result.source_tool != source_tool:
            continue
        if not result.id or result.id == "unknown" or result.id in seen:
            continue
        seen.add(result.id)
        ordered.append(result.id)
    return ordered


CANDIDATE_DETAIL_TOOL = "getCandidateDetail"
SEARCH_CANDIDATES_TOOL = "searchCandidates"
TECHNICAL_DOCUMENT_TOOL = "getCandidateTechnicalDocument"
DICTIONARY_TOOL = "getDictionary"
LEGACY_CONSULTANT_SEARCH_TOOL = "search_consultants"

# Tools whose direct output represents one or more candidates. Records
# from other direct calls (e.g. ``getDictionary`` resolving a filter,
# or ``getCandidateTechnicalDocument`` called as a non-fan-out step)
# execute for side-effect / context only and must NOT pollute the
# candidate list with non-candidate records.
_CANDIDATE_PRODUCING_TOOLS: Final[frozenset[str]] = frozenset(
    {
        SEARCH_CANDIDATES_TOOL,
        LEGACY_CONSULTANT_SEARCH_TOOL,
        CANDIDATE_DETAIL_TOOL,
    }
)

# searchCandidates field names that look like an experience filter, in
# preference order.
_EXPERIENCE_FIELD_CANDIDATES: Final[tuple[str, ...]] = (
    "experience",
    "experienceLevel",
    "experience_id",
)

# getDictionary parameter names and dictionary keys we'll try when
# asking the MCP server for the experience taxonomy.
_DICTIONARY_KEY_PARAMS: Final[tuple[str, ...]] = (
    "key",
    "name",
    "category",
    "dictionary",
    "id",
)
_EXPERIENCE_DICTIONARY_KEYS: Final[tuple[str, ...]] = (
    "experience",
    "experiences",
    "experienceLevel",
    "experienceLevels",
)


async def analyze_intent(state: GraphState, _: NodeContext) -> GraphState:
    """Interpret the natural-language query into structured intent."""
    query = state.original_query
    keywords = extract_keywords(query)
    seniority = extract_seniority(query)
    tool_hints = detect_tools(query)
    candidate_id = extract_candidate_id(query)
    min_years_experience = extract_min_years_experience(query)

    constraints: dict[str, str] = {}
    if seniority:
        constraints["seniority"] = seniority
    if candidate_id is not None:
        constraints["candidate_id"] = str(candidate_id)
    if min_years_experience is not None:
        constraints["min_experience_years"] = str(min_years_experience)

    if candidate_id is not None:
        objective = "get_candidate_detail"
    elif "search_consultants" in tool_hints:
        objective = "find_consultants"
    elif "search_projects" in tool_hints:
        objective = "find_projects"
    elif "search_opportunities" in tool_hints:
        objective = "find_opportunities"
    else:
        objective = "search_consultants"

    ambiguity: list[str] = []
    if not keywords and candidate_id is None:
        ambiguity.append("Query did not contain explicit search keywords.")

    intent = InterpretedIntent(
        objective=objective,
        entities=keywords,
        constraints=constraints,
        ambiguity_notes=ambiguity,
    )
    logger.info(
        "graph.analyze_intent",
        extra={
            "objective": objective,
            "entities": list(keywords),
            "constraints": dict(constraints),
            "ambiguity_notes": list(ambiguity),
        },
    )
    return _replace(state, interpreted_intent=intent)


async def build_plan(state: GraphState, ctx: NodeContext) -> GraphState:
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

    if intent.objective == "get_candidate_detail":
        candidate_id_str = intent.constraints.get("candidate_id")
        if candidate_id_str is None:
            # Defensive: analyze_intent should not have set this objective
            # without a candidate id, but we never call the tool blindly.
            return _replace(state, execution_plan=[])
        try:
            candidate_id_value: int = int(candidate_id_str)
        except (TypeError, ValueError):
            return _replace(state, execution_plan=[])

        # Placeholder schema: `candidateId` is our best guess. `select_tools`
        # will rewrite to `id` if the discovered schema uses that field.
        plan = [
            PlanStep(
                step=1,
                description=(
                    f"Call {CANDIDATE_DETAIL_TOOL} for candidate id "
                    f"{candidate_id_value}."
                ),
                expected_tool=CANDIDATE_DETAIL_TOOL,
                inputs={"candidateId": candidate_id_value},
            )
        ]
        return _replace(state, execution_plan=plan)

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

    plan: list[PlanStep] = []
    for index, hint in enumerate(tool_hints):
        primary, alternatives = _tool_preferences_for_hint(hint)
        plan.append(
            PlanStep(
                step=index + 1,
                description=f"Call {primary} with extracted keywords.",
                expected_tool=primary,
                alternative_tools=alternatives,
                inputs=dict(inputs),
            )
        )
    logger.info(
        "graph.build_plan",
        extra={
            "objective": intent.objective,
            "steps": [
                {
                    "step": s.step,
                    "expected_tool": s.expected_tool,
                    "alternative_tools": list(s.alternative_tools),
                }
                for s in plan
            ],
        },
    )

    event_name = "replan_created" if state.replan_count > 0 else "plan_created"
    await ctx.event_emitter.emit(
        event_name,
        {
            "plan": [_serialize_plan_step_event(s) for s in plan],
            "assumptions": list(intent.ambiguity_notes),
            "warnings": [],
        },
    )
    return _replace(state, execution_plan=plan)


# Maps the planner's internal hint (mock-era name) to a preferred real
# MCP tool with the legacy mock as a fallback. Project/opportunity hints
# stay unchanged for now — they have no documented real-tool equivalent.
_TOOL_HINT_PREFERENCES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "search_consultants": (
        SEARCH_CANDIDATES_TOOL,
        (LEGACY_CONSULTANT_SEARCH_TOOL,),
    ),
    "search_projects": ("search_projects", ()),
    "search_opportunities": ("search_opportunities", ()),
}


def _tool_preferences_for_hint(hint: str) -> tuple[str, list[str]]:
    primary, alternatives = _TOOL_HINT_PREFERENCES.get(hint, (hint, ()))
    return primary, list(alternatives)


def _schema_property_names(schema: dict[str, object]) -> set[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return set()
    return {str(name) for name in properties.keys()}


def _priority_tool_names(step: PlanStep) -> list[str]:
    """Ordered candidate tool names for a plan step (primary first)."""
    names: list[str] = []
    if step.expected_tool:
        names.append(step.expected_tool)
    for alt in step.alternative_tools:
        if alt and alt not in names:
            names.append(alt)
    return names


def _build_candidate_detail_inputs(
    current_inputs: dict[str, object],
    schema: dict[str, object],
    intent: InterpretedIntent | None,
) -> tuple[dict[str, object], list[Warning]]:
    if intent is None:
        return current_inputs, []
    candidate_id_str = intent.constraints.get("candidate_id")
    if candidate_id_str is None:
        return current_inputs, []
    try:
        candidate_id_value: int = int(candidate_id_str)
    except (TypeError, ValueError):
        return current_inputs, []

    property_names = _schema_property_names(schema)
    if "candidateId" in property_names:
        return {"candidateId": candidate_id_value}, []
    if "id" in property_names:
        return {"id": candidate_id_value}, []
    return current_inputs, []


async def _try_resolve_experience_filter(
    ctx: NodeContext,
    schema: dict[str, object],
    intent: InterpretedIntent,
    available_by_name: dict[str, McpTool],
) -> tuple[str, object] | None:
    """Resolve a years-of-experience constraint to a (field, id) pair.

    Returns ``None`` when the search schema has no experience field, or
    when ``getDictionary`` is not discovered, or when no dictionary
    entry has an unambiguous matching threshold. Never invents an id.
    """
    raw_years = intent.constraints.get("min_experience_years")
    if not raw_years:
        return None
    try:
        min_years = int(raw_years)
    except (TypeError, ValueError):
        return None

    property_names = _schema_property_names(schema)
    experience_field = next(
        (name for name in _EXPERIENCE_FIELD_CANDIDATES if name in property_names),
        None,
    )
    if experience_field is None:
        return None

    dict_tool = available_by_name.get(DICTIONARY_TOOL)
    if dict_tool is None:
        return None

    dict_properties = _schema_property_names(dict_tool.input_schema)
    # Build a small, ordered list of argument shapes worth trying. We
    # stop on the first non-empty, valid response that yields a match.
    attempt_args: list[dict[str, object]] = []
    for param in _DICTIONARY_KEY_PARAMS:
        if param in dict_properties:
            for key_value in _EXPERIENCE_DICTIONARY_KEYS:
                attempt_args.append({param: key_value})
    if not dict_properties:
        attempt_args.append({})
    if not attempt_args:
        return None

    for args in attempt_args:
        try:
            entries = await ctx.mcp_client.call_tool(DICTIONARY_TOOL, args)
        except (McpTransientError, McpToolError):
            logger.warning(
                "graph.dictionary_call_failed",
                extra={"args": args},
            )
            continue
        resolved = resolve_experience_id(entries or [], min_years)
        if resolved is not None:
            logger.info(
                "graph.experience_filter_resolved",
                extra={
                    "min_years": min_years,
                    "dictionary_args": args,
                    "resolved_id": resolved,
                    "experience_field": experience_field,
                },
            )
            return experience_field, resolved

    logger.info(
        "graph.experience_filter_not_resolved",
        extra={"min_years": min_years},
    )
    return None


async def _build_search_candidates_inputs(
    current_inputs: dict[str, object],
    schema: dict[str, object],
    intent: InterpretedIntent | None,
    ctx: NodeContext,
    available_by_name: dict[str, McpTool],
) -> tuple[dict[str, object] | None, list[Warning]]:
    """Build ``searchCandidates`` inputs or signal "skip with clarification".

    The real MCP schema expects ``keywords`` as a single string. Page
    and ``numberPerPage`` defaults are added only if at least one
    *meaningful* criterion is present (keywords or a resolved filter),
    so a broad query like "search a dev" no longer runs an empty,
    misleading search.

    Returns ``(None, warnings)`` when no meaningful criterion can be
    built; ``select_tools`` then skips this step and surfaces the
    warnings to the user.
    """
    if intent is None:
        return current_inputs, []

    property_names = _schema_property_names(schema)
    entities = [str(e).strip() for e in intent.entities if str(e).strip()]
    warnings: list[Warning] = []
    inputs: dict[str, object] = {}
    has_meaningful_criterion = False

    if "keywords" in property_names and entities:
        inputs["keywords"] = " ".join(entities)
        has_meaningful_criterion = True

    # Best-effort experience-filter resolution via getDictionary. Never
    # invents an id; only applies the filter when the resolver agrees.
    if intent.constraints.get("min_experience_years"):
        resolved = await _try_resolve_experience_filter(
            ctx, schema, intent, available_by_name
        )
        if resolved is not None:
            field_name, field_value = resolved
            inputs[field_name] = field_value
            has_meaningful_criterion = True
        else:
            warnings.append(
                Warning(
                    code="experience_filter_unmapped",
                    message=(
                        "Years-of-experience filter is not applied: no "
                        "matching dictionary entry was found for the "
                        "requested experience level."
                    ),
                )
            )

    if not has_meaningful_criterion:
        # Nothing safe to filter on. Skip the call rather than turning
        # the query into a "show me everything" browse the user didn't
        # ask for.
        warnings.append(
            Warning(
                code="clarification_needed",
                message=(
                    "Please refine your search with at least one keyword "
                    "(skill, technology, role, location, or company)."
                ),
            )
        )
        return None, warnings

    if "page" in property_names and "page" not in inputs:
        inputs["page"] = 1
    if "numberPerPage" in property_names and "numberPerPage" not in inputs:
        inputs["numberPerPage"] = 10

    return inputs, warnings


async def _resolve_step_inputs(
    tool_name: str,
    current_inputs: dict[str, object],
    schema: dict[str, object],
    intent: InterpretedIntent | None,
    ctx: NodeContext,
    available_by_name: dict[str, McpTool],
) -> tuple[dict[str, object] | None, list[Warning]]:
    if tool_name == CANDIDATE_DETAIL_TOOL:
        adjusted, warnings = _build_candidate_detail_inputs(
            current_inputs, schema, intent
        )
        return adjusted, warnings
    if tool_name == SEARCH_CANDIDATES_TOOL:
        return await _build_search_candidates_inputs(
            current_inputs, schema, intent, ctx, available_by_name
        )
    return current_inputs, []


async def select_tools(state: GraphState, ctx: NodeContext) -> GraphState:
    """Discover available MCP tools and resolve plan steps to real tools."""
    available: list[McpTool] = await ctx.mcp_client.discover_tools()
    available_by_name = {tool.name: tool for tool in available}

    await ctx.event_emitter.emit(
        "tools_discovered",
        {"tools": [_serialize_tool_entry(t) for t in available]},
    )

    selected: list[str] = []
    warnings = list(state.warnings)
    new_plan: list[PlanStep] = []
    for step in state.execution_plan:
        candidates = _priority_tool_names(step)
        if not candidates:
            new_plan.append(step)
            continue

        chosen_name = next(
            (name for name in candidates if name in available_by_name),
            None,
        )
        if chosen_name is None:
            warnings.append(
                Warning(
                    code="tool_unavailable",
                    message=(
                        f"Planned tool {candidates[0]!r} is not available."
                    ),
                )
            )
            new_plan.append(step)
            continue

        chosen_tool = available_by_name[chosen_name]
        adjusted_inputs, extra_warnings = await _resolve_step_inputs(
            chosen_name,
            step.inputs,
            chosen_tool.input_schema,
            state.interpreted_intent,
            ctx,
            available_by_name,
        )
        warnings.extend(extra_warnings)

        if adjusted_inputs is None:
            # The input builder told us this step has no meaningful
            # criteria to run on (already surfaced as a warning above).
            # Skip selecting the tool so we don't run an empty search.
            new_plan.append(
                step.model_copy(
                    update={
                        "expected_tool": chosen_name,
                        "alternative_tools": [],
                    }
                )
            )
            continue

        updates: dict[str, object] = {
            "expected_tool": chosen_name,
            "alternative_tools": [],
        }
        if adjusted_inputs != step.inputs:
            updates["inputs"] = adjusted_inputs
        new_plan.append(step.model_copy(update=updates))

        if chosen_name not in selected:
            selected.append(chosen_name)

    logger.info(
        "graph.select_tools",
        extra={
            "selected_tools": list(selected),
            "step_inputs": [
                {
                    "tool": step.expected_tool,
                    "inputs": dict(step.inputs),
                }
                for step in new_plan
                if step.expected_tool in selected
            ],
            "warning_codes": [w.code for w in warnings[len(state.warnings):]],
        },
    )

    accepted_event_steps = [
        _serialize_plan_step_event(step)
        for step in new_plan
        if step.expected_tool in selected
    ]
    new_warning_codes = {w.code for w in warnings[len(state.warnings):]}
    rejected_event_steps = [
        {
            "tool": step.expected_tool,
            "reason": "no available MCP tool matches this step",
        }
        for step in new_plan
        if step.expected_tool not in selected
        and step.expected_tool is not None
        and "tool_unavailable" in new_warning_codes
    ]
    await ctx.event_emitter.emit(
        "plan_validated",
        {
            "accepted_steps": accepted_event_steps,
            "rejected_steps": rejected_event_steps,
        },
    )

    return _replace(
        state,
        execution_plan=new_plan,
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
    (empty on failure). Emits ``tool_call_started`` before the first
    attempt and ``tool_call_completed`` after the final outcome.
    """
    await ctx.event_emitter.emit(
        "tool_call_started",
        {"tool": tool_name, "inputs": dict(inputs)},
    )

    attempt = 0
    start = time.perf_counter()
    last_error: Exception | None = None
    call: ToolCall
    raw_records: list[dict[str, object]] = []
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
            await _emit_tool_completed(ctx, call, raw_records=[])
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
            await _emit_tool_completed(ctx, call, raw_records=list(raw))
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
    await _emit_tool_completed(ctx, call, raw_records=[])
    return call, raw_records


async def _emit_tool_completed(
    ctx: NodeContext,
    call: ToolCall,
    *,
    raw_records: list[dict[str, object]] | None = None,
) -> None:
    payload: dict[str, object] = {
        "tool": call.tool,
        "status": call.status.value,
        "latency_ms": call.latency_ms,
        "result_count": call.result_count,
        "error_message": call.error_message,
    }
    if raw_records is not None:
        payload["result_shape"] = summarize_result_shape(list(raw_records))
        if ctx.debug_mode and raw_records:
            payload["result_preview"] = sanitized_preview(list(raw_records))
    await ctx.event_emitter.emit("tool_call_completed", payload)


def _inputs_for_step(state: GraphState, tool_name: str) -> dict[str, object]:
    for step in state.execution_plan:
        if step.expected_tool == tool_name:
            return dict(step.inputs)
    return {}


def _record_to_result(record: dict[str, object], source_tool: str) -> SearchResult:
    raw_score = record.get("score")
    if raw_score is None:
        # Detail-style tools return authoritative records without scoring
        # metadata. Treat them as full-confidence matches.
        score = 1.0
    else:
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
    score = max(0.0, min(1.0, score))

    # JSON:API style records nest most data under `attributes`. Resolve
    # the id and title from there as a fallback so we don't lose the
    # candidate id just because it lives in `attributes.id`.
    attributes = record.get("attributes")
    attrs_view: dict[str, object] = (
        attributes if isinstance(attributes, dict) else {}
    )

    resolved_id = record.get("id") or attrs_view.get("id")
    raw_title = record.get("title") or attrs_view.get("title")
    if not isinstance(raw_title, str) or not raw_title:
        raw_title = str(resolved_id) if resolved_id not in (None, "") else ""

    well_known = {"id", "type", "title", "snippet", "score"}
    return SearchResult(
        id=str(resolved_id) if resolved_id not in (None, "") else "",
        type=str(record.get("type", "unknown")),
        title=str(raw_title),
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

    logger.info(
        "graph.execute_mcp_tools",
        extra={
            "tool_calls": [
                {
                    "tool": c.tool,
                    "status": c.status.value,
                    "result_count": c.result_count,
                    "latency_ms": c.latency_ms,
                    "attempts": c.attempts,
                }
                for c in tool_calls[len(state.tool_calls):]
            ],
            "result_count_after_dedup": len(deduped),
        },
    )

    await _emit_results_normalized(
        ctx,
        new_tool_calls=tool_calls[len(state.tool_calls):],
        deduped=deduped,
    )

    return _replace(
        state,
        tool_calls=tool_calls,
        results=deduped,
        warnings=warnings,
        errors=errors,
    )


async def _emit_results_normalized(
    ctx: NodeContext,
    *,
    new_tool_calls: list[ToolCall],
    deduped: list[SearchResult],
) -> None:
    """Emit results_normalized with raw / search-result / card counts.

    `candidate_count` keeps its existing meaning (number of
    SearchResults) for backwards compat. `candidate_card_count`,
    `dropped_count`, and `drop_reasons` describe how the candidate
    mapper handled those SearchResults.
    """
    raw_count = sum(
        c.result_count for c in new_tool_calls if c.status is ToolCallStatus.SUCCESS
    )
    cards, dropped = candidate_cards_with_diagnostics(deduped)
    await ctx.event_emitter.emit(
        "results_normalized",
        {
            "raw_result_count": raw_count,
            "candidate_count": len(deduped),
            "candidate_ids": [r.id for r in deduped if r.id],
            "candidate_card_count": len(cards),
            "dropped_count": len(dropped),
            "drop_reasons": dropped,
        },
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

    await ctx.event_emitter.emit(
        "replan_requested",
        {
            "reason": "initial search returned no candidates",
            "previous_tools": list(state.selected_tools),
            "replan_count": state.replan_count + 1,
        },
    )

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
    return "enrich_candidates"


# Internal data keys used by enrichment so the mapper can find evidence
# without inventing fields. Prefixed with `_` so the mapper drops them.
ENRICHMENT_DETAIL_KEY: Final[str] = "_enrichment_detail"
ENRICHMENT_TECH_DOC_KEY: Final[str] = "_enrichment_technical_document"


def _candidate_id_inputs(
    candidate_id: str, schema: dict[str, object]
) -> dict[str, object]:
    """Build call inputs for a tool keyed by candidate id, honouring schema."""
    try:
        value: int | str = int(candidate_id)
    except (TypeError, ValueError):
        value = candidate_id
    properties = _schema_property_names(schema)
    if "candidateId" in properties:
        return {"candidateId": value}
    if "id" in properties:
        return {"id": value}
    return {"candidateId": value}


def _technical_query(intent: InterpretedIntent | None) -> bool:
    """Heuristic: query carries technical signal worth enriching with docs."""
    if intent is None:
        return False
    if intent.entities:
        return True
    return bool(intent.constraints.get("min_experience_years"))


def _merge_detail_into_result_data(
    target: dict[str, object], detail: dict[str, object]
) -> None:
    """Merge an MCP detail payload into a SearchResult.data dict.

    Original `target` values win on conflict so we never overwrite a
    field the search tool already returned. The full detail payload is
    also stored under an internal key for ranking-time evidence lookups.
    """
    target[ENRICHMENT_DETAIL_KEY] = detail
    for key, value in detail.items():
        if key in ("id", "type"):
            continue
        if key == "attributes" and isinstance(value, dict):
            existing = target.get("attributes")
            if isinstance(existing, dict):
                merged = dict(existing)
                for inner_key, inner_value in value.items():
                    merged.setdefault(inner_key, inner_value)
                target["attributes"] = merged
            else:
                target["attributes"] = dict(value)
            continue
        target.setdefault(key, value)


async def enrich_candidates(state: GraphState, ctx: NodeContext) -> GraphState:
    """Enrich shortlisted searchCandidates results with deeper MCP data.

    Bounded by ``ctx.max_enrichments`` so the workflow cannot fan out
    unboundedly even on large result sets. Skips silently when the
    detail tool isn't discovered (e.g. mock mode without it).
    """
    if not state.results or not state.available_tools:
        return state

    tools_by_name = {tool.name: tool for tool in state.available_tools}
    detail_tool = tools_by_name.get(CANDIDATE_DETAIL_TOOL)
    if detail_tool is None:
        return state

    eligible = [
        result
        for result in state.results
        if result.source_tool.startswith("search")
        and result.id
        and result.id != "unknown"
    ]
    if not eligible:
        return state

    enrich_with_tech_docs = (
        TECHNICAL_DOCUMENT_TOOL in tools_by_name
        and _technical_query(state.interpreted_intent)
    )
    tech_doc_schema: dict[str, object] = (
        tools_by_name[TECHNICAL_DOCUMENT_TOOL].input_schema
        if enrich_with_tech_docs
        else {}
    )

    tool_calls = list(state.tool_calls)
    enriched_results = list(state.results)

    for result in eligible[: ctx.max_enrichments]:
        # Find the result's slot in enriched_results by identity so we
        # don't accidentally update a stale copy after model_copy().
        position = next(
            (i for i, r in enumerate(enriched_results) if r is result),
            None,
        )
        if position is None:
            continue

        merged_data = dict(result.data)

        detail_inputs = _candidate_id_inputs(result.id, detail_tool.input_schema)
        detail_call, detail_raw = await _execute_single_tool(
            ctx, CANDIDATE_DETAIL_TOOL, detail_inputs
        )
        tool_calls.append(detail_call)
        if (
            detail_call.status is ToolCallStatus.SUCCESS
            and detail_raw
            and isinstance(detail_raw[0], dict)
        ):
            _merge_detail_into_result_data(merged_data, detail_raw[0])

        if enrich_with_tech_docs:
            doc_inputs = _candidate_id_inputs(result.id, tech_doc_schema)
            doc_call, doc_raw = await _execute_single_tool(
                ctx, TECHNICAL_DOCUMENT_TOOL, doc_inputs
            )
            tool_calls.append(doc_call)
            if (
                doc_call.status is ToolCallStatus.SUCCESS
                and doc_raw
                and isinstance(doc_raw[0], dict)
            ):
                merged_data[ENRICHMENT_TECH_DOC_KEY] = doc_raw[0]

        enriched_results[position] = result.model_copy(
            update={"data": merged_data}
        )

    new_calls = tool_calls[len(state.tool_calls):]
    logger.info(
        "graph.enrich_candidates",
        extra={
            "enrichment_calls": [
                {"tool": c.tool, "status": c.status.value} for c in new_calls
            ],
            "enriched_count": sum(
                1
                for r in enriched_results
                if ENRICHMENT_DETAIL_KEY in r.data
                or ENRICHMENT_TECH_DOC_KEY in r.data
            ),
        },
    )

    return _replace(state, results=enriched_results, tool_calls=tool_calls)


def _collect_strings(value: object, sink: list[str]) -> None:
    if isinstance(value, str):
        sink.append(value)
    elif isinstance(value, dict):
        for inner in value.values():
            _collect_strings(inner, sink)
    elif isinstance(value, list):
        for inner in value:
            _collect_strings(inner, sink)


def _evidence_haystack(result: SearchResult) -> str:
    """Lower-cased string view of every textual field in the result."""
    parts: list[str] = []
    if result.title:
        parts.append(result.title)
    if result.snippet:
        parts.append(result.snippet)
    _collect_strings(result.data, parts)
    return " ".join(parts).lower()


async def rank_candidates(state: GraphState, ctx: NodeContext) -> GraphState:
    """Re-rank search-tool results by evidence found in MCP fields.

    Each intent entity that appears in the candidate's combined MCP
    payload contributes a small score bump (capped). Detail/tech-doc
    enrichment also adds tiny bumps so richer evidence wins ties.
    Detail-only flows (e.g. candidate-id lookup) are untouched.
    """
    if not state.results or state.interpreted_intent is None:
        await _emit_candidate_cards_partial(ctx, state.results)
        return state

    entities = [
        entity.lower()
        for entity in state.interpreted_intent.entities
        if isinstance(entity, str) and entity.strip()
    ]
    if not entities:
        await _emit_candidate_cards_partial(ctx, state.results)
        return state

    re_ranked: list[SearchResult] = []
    for result in state.results:
        if not result.source_tool.startswith("search"):
            re_ranked.append(result)
            continue
        haystack = _evidence_haystack(result)
        matches = sum(1 for entity in entities if entity in haystack)
        bonus = min(0.5, matches * 0.1)
        if ENRICHMENT_DETAIL_KEY in result.data:
            bonus += 0.05
        if ENRICHMENT_TECH_DOC_KEY in result.data:
            bonus += 0.05
        new_score = max(0.0, min(1.0, result.score + bonus))
        re_ranked.append(result.model_copy(update={"score": new_score}))

    re_ranked.sort(key=lambda r: r.score, reverse=True)
    logger.info(
        "graph.rank_candidates",
        extra={
            "entities": list(entities),
            "ranked": [
                {"id": r.id, "source_tool": r.source_tool, "score": r.score}
                for r in re_ranked[:5]
            ],
        },
    )
    await _emit_candidate_cards_partial(ctx, re_ranked)
    return _replace(state, results=re_ranked)


async def _emit_candidate_cards_partial(
    ctx: NodeContext, results: list[SearchResult]
) -> None:
    """Surface the current candidate cards as a streaming preview event."""
    cards = candidate_cards_from_results(results)
    await ctx.event_emitter.emit(
        "candidate_cards_partial",
        {"candidates": [card.model_dump() for card in cards]},
    )


async def generate_final_response(state: GraphState, _: NodeContext) -> GraphState:
    """Produce a grounded summary string from the ranked results.

    Sorting here is idempotent: if `rank_candidates` already ordered
    the list (the normal path), this is a no-op. The sort also makes
    direct unit tests of this node deterministic without depending on
    the upstream node order.
    """
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

    logger.info(
        "graph.generate_final_response",
        extra={
            "result_count": len(ranked),
            "warning_codes": [w.code for w in state.warnings],
        },
    )

    return _replace(state, results=ranked, summary=summary)


# ---------------------------------------------------------------------------
# LLM-mode workflow nodes
# ---------------------------------------------------------------------------
#
# These nodes power the primary real-mode path: an LLM interprets the
# query and proposes a bounded tool plan, which LangGraph validates and
# executes through the same MCP client used by the deterministic path.
# The deterministic nodes above remain in place as a fallback for tests,
# mock-mode development, and when USE_LLM_PLANNER is off.
# ---------------------------------------------------------------------------


async def discover_mcp_tools(state: GraphState, ctx: NodeContext) -> GraphState:
    """Snapshot the MCP tool catalogue into state for the LLM planner."""
    available: list[McpTool] = await ctx.mcp_client.discover_tools()
    logger.info(
        "graph.discover_mcp_tools",
        extra={"tool_count": len(available), "tools": [t.name for t in available]},
    )
    await ctx.event_emitter.emit(
        "tools_discovered",
        {"tools": [_serialize_tool_entry(t) for t in available]},
    )
    return _replace(state, available_tools=available)


async def plan_with_llm(state: GraphState, ctx: NodeContext) -> GraphState:
    """Ask the LLM for a structured, validated plan over discovered tools.

    Failures of the LLM call or schema validation surface as warnings
    so the workflow can produce a user-safe response instead of crashing.
    """
    if ctx.llm_planner is None:
        # Should not happen in the LLM graph, but stay defensive.
        return _replace(
            state,
            warnings=[
                *state.warnings,
                Warning(
                    code="llm_planner_unavailable",
                    message="LLM planner is not configured.",
                ),
            ],
        )

    constraints = PlannerConstraints(
        max_plan_steps=ctx.max_plan_steps,
        max_enrichments=ctx.max_enrichments,
    )
    try:
        plan = await ctx.llm_planner.plan(
            query=state.original_query,
            filters=dict(state.filters),
            tools=list(state.available_tools),
            constraints=constraints,
            emitter=ctx.event_emitter,
        )
    except LlmPlannerError as exc:
        logger.warning("graph.plan_with_llm_failed", extra={"error": str(exc)})
        return _replace(
            state,
            warnings=[
                *state.warnings,
                Warning(
                    code="llm_plan_invalid",
                    message=(
                        "The planner could not produce a valid tool plan "
                        "for this query."
                    ),
                ),
            ],
        )

    logger.info(
        "graph.plan_with_llm",
        extra={
            "plan_steps": [
                {
                    "tool": step.tool_name,
                    "depends_on": step.depends_on,
                    "input_keys": sorted(step.inputs.keys()),
                }
                for step in plan.plan
            ],
            "assumptions": list(plan.assumptions),
        },
    )

    intent_dict = dict(plan.interpreted_intent)
    intent = InterpretedIntent(
        objective=str(intent_dict.get("objective") or "llm_plan"),
        entities=_string_list(intent_dict.get("entities")),
        constraints={
            str(k): str(v)
            for k, v in (intent_dict.get("constraints") or {}).items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)
        },
        ambiguity_notes=_string_list(intent_dict.get("ambiguity_notes"))
        or list(plan.assumptions),
    )
    extra_warnings = [
        Warning(code="llm_warning", message=msg)
        for msg in plan.warnings
        if isinstance(msg, str) and msg.strip()
    ]
    return _replace(
        state,
        interpreted_intent=intent,
        llm_plan=plan,
        warnings=[*state.warnings, *extra_warnings],
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _extract_candidate_ids(state: GraphState, source_tool: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for result in state.results:
        if result.source_tool != source_tool:
            continue
        rid = result.id
        if not rid or rid == "unknown" or rid in seen:
            continue
        seen.add(rid)
        ordered.append(rid)
    return ordered


def _candidate_id_call_inputs(
    candidate_id: str, schema: dict[str, object]
) -> dict[str, object]:
    """Pick the schema-correct argument name for a per-candidate fan-out call."""
    try:
        value: int | str = int(candidate_id)
    except (TypeError, ValueError):
        value = candidate_id
    properties = _schema_property_names(schema)
    if "candidateId" in properties:
        return {"candidateId": value}
    if "id" in properties:
        return {"id": value}
    return {"candidateId": value}


async def execute_llm_plan(state: GraphState, ctx: NodeContext) -> GraphState:
    """Execute the validated LLM plan with bounded fan-out.

    - Direct steps (no ``depends_on``) call the tool once with the
      planned inputs; each returned record becomes a SearchResult.
    - Fan-out steps (``depends_on`` set) run once per candidate id from
      the prior tool's results (capped by ``ctx.max_enrichments``) and
      MERGE the returned data into the existing SearchResult rather
      than creating duplicates.
    """
    if state.llm_plan is None or not state.llm_plan.plan:
        return state

    available_by_name = {tool.name: tool for tool in state.available_tools}
    tool_calls = list(state.tool_calls)
    results = list(state.results)
    warnings = list(state.warnings)
    errors = list(state.errors)
    selected: list[str] = list(state.selected_tools)

    for step in state.llm_plan.plan:
        tool = available_by_name.get(step.tool_name)
        if tool is None:
            warnings.append(
                Warning(
                    code="tool_unavailable",
                    message=(
                        f"Planned tool {step.tool_name!r} disappeared from "
                        "the discovered catalogue."
                    ),
                )
            )
            continue

        if step.tool_name not in selected:
            selected.append(step.tool_name)

        # Fan-out semantics: a step fans out over candidate ids ONLY
        # when it both depends on a previous step AND requests the
        # `candidate_ids` selector. A bare `depends_on` (without a
        # selector) is an ordering hint — the executor already runs
        # steps in plan order, so we treat it as a direct call.
        is_fanout = (
            step.depends_on is not None
            and step.result_selector == "candidate_ids"
        )

        if not is_fanout:
            inputs = dict(step.inputs)
            call, raw = await _execute_single_tool(ctx, step.tool_name, inputs)
            tool_calls.append(call)
            _absorb_direct_outcome(
                call, raw, step.tool_name, results, warnings, errors
            )
            continue

        # Fan-out step: pull ids from the prior tool's results and
        # enrich each matching SearchResult in place.
        fan_out_ids = _extract_candidate_ids(
            _replace(state, results=results), step.depends_on
        )[: ctx.max_enrichments]
        if not fan_out_ids:
            warnings.append(
                Warning(
                    code="fanout_skipped",
                    message=(
                        f"Skipped {step.tool_name!r}: depends_on "
                        f"{step.depends_on!r} produced no candidate ids."
                    ),
                )
            )
            continue

        target_source_tool = step.depends_on
        enrichment_marker = (
            ENRICHMENT_TECH_DOC_KEY
            if step.tool_name == TECHNICAL_DOCUMENT_TOOL
            else ENRICHMENT_DETAIL_KEY
        )

        for candidate_id in fan_out_ids:
            inputs = _candidate_id_call_inputs(candidate_id, tool.input_schema)
            # Allow the LLM to layer extra schema-valid inputs (e.g. a
            # bounded numberPerPage) but never override the fan-out key.
            for key, value in step.inputs.items():
                inputs.setdefault(key, value)
            call, raw = await _execute_single_tool(ctx, step.tool_name, inputs)
            tool_calls.append(call)
            _merge_fanout_outcome(
                call=call,
                raw_records=raw,
                source_tool=step.tool_name,
                candidate_id=candidate_id,
                target_source_tool=target_source_tool,
                enrichment_marker=enrichment_marker,
                results=results,
                warnings=warnings,
                errors=errors,
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

    logger.info(
        "graph.execute_llm_plan",
        extra={
            "tool_calls": [
                {
                    "tool": c.tool,
                    "status": c.status.value,
                    "result_count": c.result_count,
                }
                for c in tool_calls[len(state.tool_calls):]
            ],
            "result_count_after_dedup": len(deduped),
        },
    )

    await _emit_results_normalized(
        ctx,
        new_tool_calls=tool_calls[len(state.tool_calls):],
        deduped=deduped,
    )

    return _replace(
        state,
        tool_calls=tool_calls,
        results=deduped,
        warnings=warnings,
        errors=errors,
        selected_tools=selected,
    )


def _absorb_direct_outcome(
    call: ToolCall,
    raw_records: list[dict[str, object]],
    source_tool: str,
    results: list[SearchResult],
    warnings: list[Warning],
    errors: list[AgentError],
) -> None:
    """Absorb a direct tool call's outcome into the workflow state.

    Records from non-candidate-producing tools (e.g. ``getDictionary``)
    do NOT become SearchResults — they ran for ordering / context only
    and would otherwise inflate the candidate count and contaminate
    ranking.
    """
    if call.status is ToolCallStatus.SUCCESS:
        if source_tool in _CANDIDATE_PRODUCING_TOOLS:
            for record in raw_records:
                if isinstance(record, dict):
                    results.append(_record_to_result(record, source_tool))
        # Successful but non-candidate-producing call: tool_calls still
        # records the invocation (for traces and events); state.results
        # is intentionally untouched.
    elif call.status is ToolCallStatus.FAILED:
        warnings.append(
            Warning(
                code="tool_failed",
                message=(
                    f"Tool {source_tool!r} could not be executed reliably; "
                    "results may be incomplete."
                ),
            )
        )
        errors.append(
            AgentError(
                code="tool_call_failed",
                message=call.error_message or "tool call failed",
                node="execute_llm_plan",
                details={"tool": source_tool},
            )
        )


def _merge_fanout_outcome(
    *,
    call: ToolCall,
    raw_records: list[dict[str, object]],
    source_tool: str,
    candidate_id: str,
    target_source_tool: str,
    enrichment_marker: str,
    results: list[SearchResult],
    warnings: list[Warning],
    errors: list[AgentError],
) -> None:
    """Merge fan-out call results into the matching base SearchResult.

    Never appends a new SearchResult — fan-out is enrichment of an
    existing candidate, not a separate candidate.
    """
    if call.status is ToolCallStatus.FAILED:
        warnings.append(
            Warning(
                code="tool_failed",
                message=(
                    f"Enrichment tool {source_tool!r} failed for candidate "
                    f"{candidate_id!r}; partial enrichment only."
                ),
            )
        )
        errors.append(
            AgentError(
                code="tool_call_failed",
                message=call.error_message or "tool call failed",
                node="execute_llm_plan",
                details={"tool": source_tool, "candidate_id": candidate_id},
            )
        )
        return

    if call.status is not ToolCallStatus.SUCCESS or not raw_records:
        return

    target_idx = next(
        (
            i
            for i, r in enumerate(results)
            if r.source_tool == target_source_tool and r.id == candidate_id
        ),
        None,
    )
    if target_idx is None:
        return

    target = results[target_idx]
    merged_data = dict(target.data)
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        if enrichment_marker == ENRICHMENT_TECH_DOC_KEY:
            merged_data[ENRICHMENT_TECH_DOC_KEY] = record
        else:
            _merge_detail_into_result_data(merged_data, record)
    results[target_idx] = target.model_copy(update={"data": merged_data})
