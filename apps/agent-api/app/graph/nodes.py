"""LangGraph nodes for the Plan-and-Execute search workflow.

Each node is a small async function operating on the typed
`GraphState` model. Nodes return a new state instance (immutable
update) so the graph remains side-effect free.
"""

from __future__ import annotations

import logging
import re
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
    candidate_full_name,
)
from app.services.dictionary_resolver import (
    dictionary_activity_area_option_entries,
    dictionary_availability_entries,
    dictionary_candidate_state_entries,
    dictionary_contract_entries,
    dictionary_language_level_entries,
    dictionary_language_spoken_entries,
    dictionary_mobility_option_entries,
    dictionary_section_entries,
    dictionary_tool_entries,
    resolve_excluded_state_ids,
    resolve_experience_id,
    resolve_label_for_id,
    resolve_tool_ids,
)
from app.services.search_strategy import (
    RANKING_CRITERIA,
    build_recall_passes,
    classify_anchors,
    evidence_score,
    parse_years,
)
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
from app.services.semantic_scorer import SemanticScorer
from app.agents.agent1.normalizer import (
    normalize_candidates as _agent1_normalize,
    NORM_EXPERIENCE_YEARS,
    NORM_SKILLS,
    NORM_LANGUAGES,
    NORM_TITLE,
)


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
    use_llm_replan: bool = True
    replan_skip_score: float = 0.8
    event_emitter: EventEmitter = field(default_factory=NoopEventEmitter)
    debug_mode: bool = False
    semantic_scorer: SemanticScorer | None = None
    semantic_boost_weight: float = 0.15


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
    # Extract technical/skill terms (removes stopwords, type hints like "dev"/"candidat").
    # Space-separated terms let BoondManager score by relevance without forcing strict AND.
    extracted = extract_keywords(query)
    keywords = extracted if extracted else []
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
        inputs["numberPerPage"] = 8

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
        # Search-style tools return candidates whose relevance is UNKNOWN
        # until evidence is checked in ranking — they must earn their score
        # there, not be presented as full-confidence matches. Detail-style
        # by-id lookups (e.g. getCandidateDetail) are authoritative, so they
        # stay full-confidence.
        score = 0.0 if source_tool.startswith("search") else 1.0
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
    technical = record.get("technicalDocument")
    technical_data: dict[str, object] = (
        technical if isinstance(technical, dict) else {}
    )

    resolved_id = record.get("id") or attrs_view.get("id")
    full_name = " ".join(
        str(part)
        for part in (
            record.get("firstName") or attrs_view.get("firstName"),
            record.get("lastName") or attrs_view.get("lastName"),
        )
        if part
    ).strip()
    raw_title = (
        record.get("title")
        or attrs_view.get("title")
        or technical_data.get("title")
        or full_name
        or record.get("email")
        or attrs_view.get("email")
    )
    if not isinstance(raw_title, str) or not raw_title:
        raw_title = str(resolved_id) if resolved_id not in (None, "") else ""

    raw_snippet = (
        record.get("snippet")
        or attrs_view.get("snippet")
        or technical_data.get("skills")
        or technical_data.get("tools")
        or ""
    )

    well_known = {"id", "type", "title", "snippet", "score"}
    return SearchResult(
        id=str(resolved_id) if resolved_id not in (None, "") else "",
        type=str(record.get("type") or attrs_view.get("type") or "consultant"),
        title=str(raw_title),
        snippet=str(raw_snippet),
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

            # For candidate keyword searches, run a second pass on title+skills
            # so candidates whose profile title matches (e.g. "Tech Lead Java backend")
            # are found even when their CV text doesn't contain the exact keywords.
            if tool_name == SEARCH_CANDIDATES_TOOL and inputs.get("keywords"):
                title_inputs = {**inputs, "keywordsType": "titleSkills"}
                title_call, title_records = await _execute_single_tool(
                    ctx, tool_name, title_inputs
                )
                tool_calls.append(title_call)
                if title_call.status is ToolCallStatus.SUCCESS:
                    for record in title_records:
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


def _results_already_strong(state: GraphState, skip_score: float) -> bool:
    """True when the ranked results are good enough to skip reflection.

    A full match anywhere, or a top score at/above ``skip_score``, means another
    search is unlikely to help — so we don't spend a reflection LLM call.
    """
    if not state.results:
        return False
    if any(r.is_full_match for r in state.results):
        return True
    return max((r.score for r in state.results), default=0.0) >= skip_score


def _reflection_results_summary(state: GraphState, *, limit: int = 8) -> str:
    """Compact, grounded rows for the reflection prompt (no raw MCP payloads)."""
    lines: list[str] = []
    for result in state.results[:limit]:
        if not result.source_tool.startswith("search"):
            continue
        name = candidate_full_name(result) or result.id
        title = result.title or ""
        unmet = ", ".join(result.unmet_criteria) if result.unmet_criteria else "none"
        lines.append(
            f"- {name} — {title} | score={round(result.score, 3)} "
            f"| full_match={bool(result.is_full_match)} | unmet=[{unmet}]"
        )
    return "\n".join(lines) if lines else "(no candidates returned)"


async def reflect_on_results(state: GraphState, ctx: NodeContext) -> GraphState:
    """LLM-driven replan decision (bounded reflection).

    The LLM judges the ranked candidates and decides whether one more, guided
    search pass is warranted. Deterministic gates run first so the reflection
    LLM call is skipped when it cannot or should not help — and the loop can
    never exceed ``max_replan_attempts`` regardless of what the LLM says.
    """
    if not ctx.use_llm_replan:
        return state
    if ctx.max_replan_attempts <= 0 or state.replan_count >= ctx.max_replan_attempts:
        return state
    reflect = getattr(ctx.llm_planner, "reflect", None)
    if reflect is None:
        return state
    if _results_already_strong(state, ctx.replan_skip_score):
        return state

    try:
        verdict = await reflect(
            query=state.original_query,
            results_summary=_reflection_results_summary(state),
            emitter=ctx.event_emitter,
        )
    except Exception as exc:  # noqa: BLE001 — fail safe: never loop on error
        logger.warning("graph.reflect_failed", extra={"error": str(exc)})
        return state

    guidance = (getattr(verdict, "guidance", "") or "").strip()
    if not getattr(verdict, "needs_replan", False) or not guidance:
        return state

    await ctx.event_emitter.emit(
        "replan_requested",
        {
            "reason": (getattr(verdict, "reason", "") or "")[:300],
            "guidance": guidance[:300],
            "replan_count": state.replan_count + 1,
            "decided_by": "llm",
        },
    )
    return _replace(
        state,
        replan_count=state.replan_count + 1,
        replan_feedback=guidance,
    )


def should_replan_llm(state: GraphState) -> str:
    """Conditional edge: loop back to plan_with_llm when a replan is pending.

    ``replan_feedback`` is the single signal; it is set only by
    ``reflect_on_results`` under budget and cleared by ``plan_with_llm`` on
    consumption, so the loop is bounded and cannot spin.
    """
    if state.replan_feedback.strip():
        return "plan_with_llm"
    return "generate_final_response"


# Internal data keys used by enrichment so the mapper can find evidence
# without inventing fields. Prefixed with `_` so the mapper drops them.
ENRICHMENT_DETAIL_KEY: Final[str] = "_enrichment_detail"
ENRICHMENT_TECH_DOC_KEY: Final[str] = "_enrichment_technical_document"
ENRICHMENT_RESUME_KEY: Final[str] = "_enrichment_resume"
ENRICHMENT_ADMINISTRATIVE_KEY: Final[str] = "_enrichment_administrative"
EXPERIENCE_MIN_YEARS_KEY: Final[str] = "experienceMinYears"
RESUME_TOOL: Final[str] = "getCandidateCV"
ADMINISTRATIVE_TOOL: Final[str] = "getCandidateAdministrative"

# Resolved human-readable label keys stored in result.data for display
AVAILABILITY_LABEL_KEY: Final[str] = "_availabilityLabel"
EXPERIENCE_LABEL_KEY: Final[str] = "_experienceLabel"
CONTRACT_LABEL_KEY: Final[str] = "_contractLabel"
MOBILITY_LABEL_KEY: Final[str] = "_mobilityLabel"
RESOLVED_TOOL_LABELS_KEY: Final[str] = "_resolvedToolLabels"
STATE_LABEL_KEY: Final[str] = "_stateLabel"
RESOLVED_LANGUAGE_LABELS_KEY: Final[str] = "_resolvedLanguageLabels"
RESOLVED_ACTIVITY_AREA_LABELS_KEY: Final[str] = "_resolvedActivityAreaLabels"


def _raw_availability(data: dict[str, object]) -> object | None:
    raw = data.get("availability")
    if raw is None:
        attrs = data.get("attributes")
        if isinstance(attrs, dict):
            raw = attrs.get("availability")
    return raw


def _raw_experience_id(data: dict[str, object]) -> object | None:
    for source in (data, data.get("attributes"), data.get(ENRICHMENT_TECH_DOC_KEY)):
        if isinstance(source, dict):
            raw = source.get("experience")
            if raw is not None:
                return raw
    return None


def _contract_value_from_source(source: object) -> object | None:
    if not isinstance(source, dict):
        return None
    for field in ("desiredContract", "contractType", "typeOf", "contract"):
        raw = source.get(field)
        if raw is not None:
            return raw
    attrs = source.get("attributes")
    if isinstance(attrs, dict):
        for field in ("desiredContract", "contractType", "typeOf", "contract"):
            raw = attrs.get(field)
            if raw is not None:
                return raw
    return None


def _raw_contract_type(data: dict[str, object]) -> object | None:
    # Administrative endpoint is the authoritative source for desired contract type
    # (typeOf / contractType from /candidates/{id}/administrative).
    # Only fall back to /information if administrative was not fetched.
    if ENRICHMENT_ADMINISTRATIVE_KEY in data:
        raw = _contract_value_from_source(data.get(ENRICHMENT_ADMINISTRATIVE_KEY))
        if raw is not None:
            return raw
        # Administrative was fetched but contractType is null/absent — stop here.
        # Do not fall back to /information typeOf which is a resource-type ID,
        # not the desired contract type.
        return None

    # Administrative not fetched: try detail as secondary source, then search summary.
    if ENRICHMENT_DETAIL_KEY in data:
        return _contract_value_from_source(data.get(ENRICHMENT_DETAIL_KEY))

    for source in (data, data.get("attributes")):
        raw = _contract_value_from_source(source)
        if raw is not None:
            return raw
    return None


def _inject_resolved_labels(
    data: dict[str, object],
    avail_entries: list[dict[str, object]],
    exp_entries: list[dict[str, object]],
    contract_entries: list[dict[str, object]] | None = None,
    mobility_entries: list[dict[str, object]] | None = None,
    tool_entries: list[dict[str, object]] | None = None,
    state_entries: list[dict[str, object]] | None = None,
    language_spoken_entries: list[dict[str, object]] | None = None,
    language_level_entries: list[dict[str, object]] | None = None,
    activity_area_entries: list[dict[str, object]] | None = None,
) -> None:
    """Resolve BoondManager integer IDs to human-readable labels in-place."""
    if AVAILABILITY_LABEL_KEY not in data and avail_entries:
        raw_avail = _raw_availability(data)
        if raw_avail is not None:
            label = resolve_label_for_id(avail_entries, raw_avail)
            if label:
                data[AVAILABILITY_LABEL_KEY] = label

    if EXPERIENCE_LABEL_KEY not in data and exp_entries:
        raw_exp = _raw_experience_id(data)
        if raw_exp is not None:
            label = resolve_label_for_id(exp_entries, raw_exp)
            if label:
                data[EXPERIENCE_LABEL_KEY] = label

    if CONTRACT_LABEL_KEY not in data and contract_entries:
        raw_contract = _raw_contract_type(data)
        if raw_contract is not None:
            label = resolve_label_for_id(contract_entries, raw_contract)
            if label:
                data[CONTRACT_LABEL_KEY] = label

    if STATE_LABEL_KEY not in data and state_entries:
        raw_state = data.get("state")
        if raw_state is None:
            attrs = data.get("attributes")
            if isinstance(attrs, dict):
                raw_state = attrs.get("state")
        if raw_state is not None:
            label = resolve_label_for_id(state_entries, raw_state)
            if label:
                data[STATE_LABEL_KEY] = label

    if MOBILITY_LABEL_KEY not in data and mobility_entries:
        raw_areas: object = data.get("mobilityAreas")
        if raw_areas is None:
            attrs = data.get("attributes")
            if isinstance(attrs, dict):
                raw_areas = attrs.get("mobilityAreas")
        if isinstance(raw_areas, list) and raw_areas:
            labels = [
                resolve_label_for_id(mobility_entries, area_id) or str(area_id)
                for area_id in raw_areas if area_id
            ]
            labels = [lb for lb in labels if lb]
            if labels:
                data[MOBILITY_LABEL_KEY] = ", ".join(labels[:3])

    if RESOLVED_TOOL_LABELS_KEY not in data and tool_entries:
        resolved: list[str] = []
        for source_key in (ENRICHMENT_TECH_DOC_KEY, "tools"):
            source = data.get(source_key)
            if isinstance(source, dict):
                raw_tools = source.get("tools")
            elif isinstance(source, list):
                raw_tools = source
            else:
                raw_tools = None
            if not isinstance(raw_tools, list):
                continue
            for item in raw_tools:
                if isinstance(item, dict):
                    tool_id = item.get("tool")
                    if tool_id:
                        label = resolve_label_for_id(tool_entries, tool_id)
                        name = label or str(tool_id)
                        if name and name not in resolved:
                            resolved.append(name)
                elif isinstance(item, str) and item:
                    label = resolve_label_for_id(tool_entries, item)
                    name = label or item
                    if name and name not in resolved:
                        resolved.append(name)
        if resolved:
            data[RESOLVED_TOOL_LABELS_KEY] = resolved

    if RESOLVED_LANGUAGE_LABELS_KEY not in data and (
        language_spoken_entries or language_level_entries
    ):
        raw_languages = data.get("languages")
        if raw_languages is None:
            tech = data.get(ENRICHMENT_TECH_DOC_KEY)
            if isinstance(tech, dict):
                raw_languages = tech.get("languages")
        if isinstance(raw_languages, list):
            resolved_languages: list[dict[str, object]] = []
            for item in raw_languages:
                if not isinstance(item, dict):
                    continue
                raw_language = item.get("language") or item.get("name")
                raw_level = item.get("level")
                language = (
                    resolve_label_for_id(language_spoken_entries or [], raw_language)
                    or (str(raw_language).strip() if raw_language else None)
                )
                level = (
                    resolve_label_for_id(language_level_entries or [], raw_level)
                    or (str(raw_level).strip() if raw_level else None)
                )
                if language:
                    entry: dict[str, object] = {"language": language}
                    if level:
                        entry["level"] = level
                    resolved_languages.append(entry)
            if resolved_languages:
                data[RESOLVED_LANGUAGE_LABELS_KEY] = resolved_languages

    if RESOLVED_ACTIVITY_AREA_LABELS_KEY not in data and activity_area_entries:
        raw_areas_act = data.get("activityAreas")
        if raw_areas_act is None:
            tech = data.get(ENRICHMENT_TECH_DOC_KEY)
            if isinstance(tech, dict):
                raw_areas_act = tech.get("activityAreas")
        if isinstance(raw_areas_act, list):
            labels_act = [
                resolve_label_for_id(activity_area_entries, area_id) or str(area_id)
                for area_id in raw_areas_act if area_id
            ]
            labels_act = [lb for lb in labels_act if lb]
            if labels_act:
                data[RESOLVED_ACTIVITY_AREA_LABELS_KEY] = labels_act


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
    # detail_tool may be None in mock mode — CV/admin enrichment still runs.

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
        and (ctx.llm_planner is not None or _technical_query(state.interpreted_intent))
    )
    tech_doc_schema: dict[str, object] = (
        tools_by_name[TECHNICAL_DOCUMENT_TOOL].input_schema
        if enrich_with_tech_docs
        else {}
    )
    enrich_with_resume = RESUME_TOOL in tools_by_name
    resume_schema: dict[str, object] = (
        tools_by_name[RESUME_TOOL].input_schema if enrich_with_resume else {}
    )
    enrich_with_administrative = ADMINISTRATIVE_TOOL in tools_by_name
    administrative_schema: dict[str, object] = (
        tools_by_name[ADMINISTRATIVE_TOOL].input_schema
        if enrich_with_administrative
        else {}
    )

    # Fetch dictionary once for label resolution (availability, experience,
    # contract, mobility, etc.). On the LLM path the dictionary may have
    # already been called for filter resolution, but its content wasn't stored
    # in state — we fetch it again here only if the tool is available.
    dict_raw: list[dict[str, object]] = []
    if DICTIONARY_TOOL in tools_by_name:
        fetched = await _fetch_dictionary(ctx, tools_by_name)
        if fetched:
            dict_raw = fetched
    avail_entries = dictionary_availability_entries(dict_raw)
    exp_entries = dictionary_section_entries(dict_raw, "experience")
    contract_entries = dictionary_contract_entries(dict_raw)
    mobility_entries = dictionary_mobility_option_entries(dict_raw)
    tool_entries = dictionary_tool_entries(dict_raw)
    state_entries = dictionary_candidate_state_entries(dict_raw)
    language_spoken_entries = dictionary_language_spoken_entries(dict_raw)
    language_level_entries = dictionary_language_level_entries(dict_raw)
    activity_area_entries = dictionary_activity_area_option_entries(dict_raw)

    # Remove candidates with excluded states ("Ne plus contacter", "A SUPPRIMER", etc.)
    # before enrichment so we never surface them to the frontend.
    excluded_state_ids = {str(sid) for sid in resolve_excluded_state_ids(state_entries)}
    if excluded_state_ids:
        def _is_excluded(result: SearchResult) -> bool:
            raw_state = result.data.get("state")
            if raw_state is None:
                attrs = result.data.get("attributes")
                if isinstance(attrs, dict):
                    raw_state = attrs.get("state")
            return raw_state is not None and str(raw_state) in excluded_state_ids

        eligible = [r for r in eligible if not _is_excluded(r)]
        excluded_ids = {r.id for r in state.results if _is_excluded(r)}
    else:
        excluded_ids: set[str] = set()

    tool_calls = list(state.tool_calls)
    enriched_results = [r for r in state.results if r.id not in excluded_ids]

    enrichment_limit = len(eligible) if ctx.llm_planner is not None else ctx.max_enrichments

    for result in eligible[:enrichment_limit]:
        # Find the result's slot in enriched_results by identity so we
        # don't accidentally update a stale copy after model_copy().
        position = next(
            (i for i, r in enumerate(enriched_results) if r is result),
            None,
        )
        if position is None:
            continue

        merged_data = dict(result.data)

        if detail_tool is not None and ENRICHMENT_DETAIL_KEY not in merged_data:
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

        if enrich_with_tech_docs and ENRICHMENT_TECH_DOC_KEY not in merged_data:
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

        if enrich_with_resume and ENRICHMENT_RESUME_KEY not in merged_data:
            resume_inputs = _candidate_id_inputs(result.id, resume_schema)
            resume_call, resume_raw = await _execute_single_tool(
                ctx, RESUME_TOOL, resume_inputs
            )
            tool_calls.append(resume_call)
            if (
                resume_call.status is ToolCallStatus.SUCCESS
                and resume_raw
                and isinstance(resume_raw[0], dict)
                and resume_raw[0].get("hasContent")
            ):
                merged_data[ENRICHMENT_RESUME_KEY] = dict(resume_raw[0])

        if enrich_with_administrative and ENRICHMENT_ADMINISTRATIVE_KEY not in merged_data:
            admin_inputs = _candidate_id_inputs(result.id, administrative_schema)
            admin_call, admin_raw = await _execute_single_tool(
                ctx, ADMINISTRATIVE_TOOL, admin_inputs
            )
            tool_calls.append(admin_call)
            if (
                admin_call.status is ToolCallStatus.SUCCESS
                and admin_raw
                and isinstance(admin_raw[0], dict)
            ):
                merged_data[ENRICHMENT_ADMINISTRATIVE_KEY] = admin_raw[0]

        _inject_resolved_labels(
            merged_data, avail_entries, exp_entries,
            contract_entries, mobility_entries, tool_entries,
            state_entries, language_spoken_entries,
            language_level_entries, activity_area_entries,
        )

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


async def normalize_candidates(state: GraphState, ctx: NodeContext) -> GraphState:
    """Agent1 — normalise candidate data quality before matching.

    Compares the same information across BoondManager structured fields, CV
    text, and technical document, then writes a ``_normalized_*`` view into
    each result's data dict.  Agent0's matching (``rank_candidates``) reads
    those normalised keys so it never scores raw, incomplete BoondManager data.
    """
    if not state.results:
        return state

    normalised = _agent1_normalize(state.results)

    logger.info(
        "graph.normalize_candidates",
        extra={"count": len(normalised)},
    )

    return _replace(state, results=normalised)


def _collect_strings(value: object, sink: list[str]) -> None:
    if isinstance(value, str):
        sink.append(value)
    elif isinstance(value, dict):
        for inner in value.values():
            _collect_strings(inner, sink)
    elif isinstance(value, list):
        for inner in value:
            _collect_strings(inner, sink)


# Skill-relevant top-level fields from the BoondManager search payload.
_SKILL_SURFACE_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "jobTitle",
    "headline",
    "position",
    "summary",
    "description",
    "skills",
    "tools",
    "expertiseAreas",
    "activityAreas",
    "languages",
)

# Skill-relevant fields within the enrichment tech-doc payload.
_TECH_DOC_SKILL_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "summary",
    "description",
    "text",
    "skills",
    "tools",
    "expertiseAreas",
    "activityAreas",
    "diplomas",
    "training",
)


def _evidence_haystack(result: SearchResult) -> str:
    """Lower-cased string built only from skill-relevant fields.

    Restricted to job title, skills, expertise, and tech-doc content so that
    incidental strings in metadata fields (email, IDs, company names, addresses)
    do not produce false skill matches.
    """
    parts: list[str] = []
    if result.title:
        parts.append(result.title)
    if result.snippet:
        parts.append(result.snippet)
    flat = _flatten_for_domain(result.data)
    for field in _SKILL_SURFACE_FIELDS:
        value = flat.get(field)
        if value:
            _collect_strings(value, parts)
    # Include tech doc skill fields when available.
    tech = result.data.get(ENRICHMENT_TECH_DOC_KEY)
    if isinstance(tech, dict):
        for field in _TECH_DOC_SKILL_FIELDS:
            value = tech.get(field)
            if value:
                _collect_strings(value, parts)
    # Include CV extracted text via the dedicated reader.
    resume_text = _resume_haystack(result)
    if resume_text:
        parts.append(resume_text)
    # Include Agent1 normalised skills and languages (may add entries absent
    # from BoondManager structured fields).
    norm_skills = result.data.get(NORM_SKILLS)
    if isinstance(norm_skills, list):
        _collect_strings(norm_skills, parts)
    norm_langs = result.data.get(NORM_LANGUAGES)
    if isinstance(norm_langs, list):
        _collect_strings(norm_langs, parts)
    return " ".join(parts).lower()


_DOMAIN_CONSTRAINT_KEYS: Final[tuple[str, ...]] = (
    "domain",
    "last_experience_company",
    "company",
    "sector",
    "business_context",
)


def _domain_terms(constraints: dict[str, str]) -> tuple[str, ...]:
    terms: list[str] = []
    for key in _DOMAIN_CONSTRAINT_KEYS:
        value = constraints.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in terms:
            terms.append(value.strip())
    return tuple(terms)


def _ranking_priority(constraints: dict[str, str]) -> tuple[str, ...] | None:
    """LLM-supplied ranking ordering, parsed and validated.

    ``constraints.ranking_priority`` is a comma-separated, most-important-first
    list of criterion keys. Keep only known keys (``RANKING_CRITERIA``),
    de-duplicated in order; return ``None`` when absent/empty so the ranker
    falls back to its default weights.
    """
    raw = constraints.get("ranking_priority")
    if not isinstance(raw, str) or not raw.strip():
        return None
    ordered: list[str] = []
    for token in raw.split(","):
        key = "".join(ch for ch in token.lower() if ch.isalpha())
        if key in RANKING_CRITERIA and key not in ordered:
            ordered.append(key)
    return tuple(ordered) or None


def _summary_haystack(result: SearchResult) -> str:
    """The candidate's SUMMARY surface: title/snippet + search-summary data.

    Excludes the ``_``-prefixed enrichment payloads (technical document /
    detail), so a criterion found here is "visible" on the search summary
    even before any technical-document confirmation.
    """
    parts: list[str] = []
    if result.title:
        parts.append(result.title)
    if result.snippet:
        parts.append(result.snippet)
    safe = {
        k: v
        for k, v in result.data.items()
        if not (isinstance(k, str) and k.startswith("_"))
    }
    _collect_strings(safe, parts)
    return " ".join(parts).lower()


def _techdoc_haystack(result: SearchResult) -> str:
    """Text from the candidate's technical-document enrichment payload only."""
    payload = result.data.get(ENRICHMENT_TECH_DOC_KEY)
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    _collect_strings(payload, parts)
    return " ".join(parts).lower()


def _resume_haystack(result: SearchResult) -> str:
    """Raw CV text extracted from the candidate's PDF resume."""
    payload = result.data.get(ENRICHMENT_RESUME_KEY)
    if not isinstance(payload, dict):
        return ""
    text = payload.get("extractedText") or payload.get("text") or ""
    return text.lower() if isinstance(text, str) else ""


def _min_years_in(source: object) -> int | None:
    """Read an ``experienceMinYears`` value from a record/dict, if present."""
    if not isinstance(source, dict):
        return None
    for key in ("experienceMinYears", "experience_min_years"):
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                continue
    return None


def _record_experience_min_years(result: SearchResult) -> int | None:
    """Best years-of-experience estimate for the candidate (or None).

    Prefers Agent1's normalised value (cross-validated across BoondManager,
    CV, and technical document) over the raw BoondManager figure.
    """
    # Agent1 normalised value takes precedence.
    norm = result.data.get(NORM_EXPERIENCE_YEARS)
    if isinstance(norm, int) and norm > 0:
        return norm

    for source in (
        result.data,
        result.data.get("attributes"),
        result.data.get(ENRICHMENT_TECH_DOC_KEY),
    ):
        years = _min_years_in(source)
        if years is not None:
            return years
    return None


def _techdoc_min_years(result: SearchResult) -> int | None:
    """experienceMinYears from the technical-document enrichment payload only."""
    return _min_years_in(result.data.get(ENRICHMENT_TECH_DOC_KEY))


# Free-text business-context fields. Domain evidence is matched against
# these high-signal surfaces (title/job-title, summary, description) rather
# than the raw skills/tools blob, so an incidental business word in a long
# skills list does not earn domain credit.
_DOMAIN_TEXT_FIELDS: Final[tuple[str, ...]] = ("summary", "description")
_DOMAIN_SURFACE_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "jobTitle",
    "headline",
    "position",
    "summary",
    "description",
)


def _flatten_for_domain(data: dict[str, object]) -> dict[str, object]:
    """Hoist JSON:API ``attributes`` so title/summary lookups don't miss them."""
    flat = dict(data)
    attributes = data.get("attributes")
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            flat.setdefault(key, value)
    return flat


def _summary_domain_text(result: SearchResult) -> str:
    """High-signal SUMMARY domain surface: title/job-title + summary/description."""
    parts: list[str] = []
    if result.title:
        parts.append(result.title)
    if result.snippet:
        parts.append(result.snippet)
    flat = _flatten_for_domain(result.data)
    for field in _DOMAIN_SURFACE_FIELDS:
        value = flat.get(field)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def _techdoc_domain_text(result: SearchResult) -> str:
    """Technical-document free-text (summary/description) for domain evidence."""
    payload = result.data.get(ENRICHMENT_TECH_DOC_KEY)
    if not isinstance(payload, dict):
        return ""
    parts = [
        str(payload[field])
        for field in _DOMAIN_TEXT_FIELDS
        if isinstance(payload.get(field), str)
    ]
    return " ".join(parts).lower()


def _domain_haystack(result: SearchResult) -> str:
    """High-signal domain surface for scoring: summary text + tech-doc text."""
    summary = _summary_domain_text(result)
    techdoc = _techdoc_domain_text(result)
    return f"{summary} {techdoc}".strip()


def _criteria_status(
    results: list[SearchResult],
    *,
    skills: tuple[str, ...],
    domains: tuple[str, ...],
    role: str | None,
    required_years: int | None,
) -> tuple[list[str], list[str]]:
    """Classify each requested criterion across candidates.

    Returns ``(missing, visible_unverified)`` human-readable label lists:
    - **verified** — evidenced in some candidate's technical document (omitted),
    - **visible** — evidenced only in a summary/title (e.g. CIB in a job title),
    - **missing** — evidenced nowhere.
    Labels preserve the user's original term (acronym intact).
    """
    verified: set[str] = set()
    visible: set[str] = set()
    for result in results:
        if not result.source_tool.startswith("search"):
            continue
        techdoc = _techdoc_haystack(result)
        if techdoc:
            td_years = _techdoc_min_years(result)
            _, td_hits = evidence_score(
                techdoc,
                skills=skills,
                domains=domains,
                role=role,
                candidate_min_years=(
                    td_years if td_years is not None else parse_years(techdoc)
                ),
                required_min_years=required_years,
                domain_haystack=_techdoc_domain_text(result),
            )
            verified |= td_hits
        resume = _resume_haystack(result)
        if resume:
            _, cv_hits = evidence_score(
                resume,
                skills=skills,
                domains=domains,
                role=role,
                candidate_min_years=parse_years(resume),
                required_min_years=required_years,
                domain_haystack=resume,
            )
            verified |= cv_hits
        summary = _summary_haystack(result)
        _, sm_hits = evidence_score(
            summary,
            skills=skills,
            domains=domains,
            role=role,
            candidate_min_years=_record_experience_min_years(result),
            required_min_years=required_years,
            domain_haystack=_summary_domain_text(result),
        )
        visible |= sm_hits

    missing: list[str] = []
    visible_only: list[str] = []

    def _classify(key: str, label: str) -> None:
        if key in verified:
            return
        (visible_only if key in visible else missing).append(label)

    for skill in skills:
        _classify(f"skill:{skill.lower()}", skill)
    if domains:
        _classify("domain", ", ".join(domains))
    if role:
        _classify("role", role)
    if required_years is not None:
        _classify("seniority", f"{required_years}+ years")
    return missing, visible_only


def _evaluate_match(
    hits: set[str],
    *,
    skills: tuple[str, ...],
    domains: tuple[str, ...],
    role: str | None,
    required_years: int | None,
    requested_name: str | None = None,
) -> tuple[bool, list[str]]:
    """Strict per-candidate match from its evidence ``hits``.

    Full match iff EVERY requested criterion is evidenced for the candidate
    (unknown counts as not evidenced). Returns ``(is_full_match, unmet)`` with
    human labels (original casing / verbatim domain term) for the criteria
    not evidenced — same labels as the aggregate status.
    """
    unmet: list[str] = []
    if requested_name and "name" not in hits:
        unmet.append(requested_name)
    for skill in skills:
        if f"skill:{skill.lower()}" not in hits:
            unmet.append(skill)
    if domains and "domain" not in hits:
        unmet.append(", ".join(domains))
    if role and "role" not in hits:
        unmet.append(role)
    if required_years is not None and "seniority" not in hits:
        unmet.append(f"{required_years}+ years")
    return (not unmet), unmet


async def rank_candidates(state: GraphState, ctx: NodeContext) -> GraphState:
    """Rank search-tool results by weighted, multi-criteria evidence.

    Distinct criteria are scored separately — skill/role anchors, the
    domain/business-context signal (e.g. CIB / banking found in the
    title or technical document), and seniority (the candidate's known
    experience meeting the requested minimum). A profile that matches more
    criteria — especially seniority and domain — outranks a bare skill
    match, so a 3-year Java profile never ties a 10+-year Java+CIB one.

    Criteria never evidenced on any candidate are recorded as
    ``criteria_unverified`` so the user-facing message stays honest.
    """
    if not state.results or state.interpreted_intent is None:
        await _emit_candidate_cards_partial(ctx, state.results)
        return state

    intent = state.interpreted_intent
    skills = tuple(
        e.strip() for e in intent.entities if isinstance(e, str) and e.strip()
    )
    domains = _domain_terms(intent.constraints)
    role = intent.constraints.get("role") or None
    required_years = _int_or_none(intent.constraints.get("min_experience_years"))
    requested_name = (intent.constraints.get("name") or "").strip()
    # The LLM may order the criteria by importance; the deterministic ranker
    # derives its weights from that ordering (off-vocabulary keys are dropped).
    priority = _ranking_priority(intent.constraints)
    if not (skills or domains or role or required_years is not None or requested_name):
        await _emit_candidate_cards_partial(ctx, state.results)
        return state

    # Collect semantic boosts asynchronously upfront when scorer is available.
    semantic_boosts: dict[str, float] = {}
    if ctx.semantic_scorer is not None and (skills or domains):
        query_terms = list(skills) + list(domains)
        for result in state.results:
            if not result.source_tool.startswith("search"):
                continue
            haystack = _evidence_haystack(result)
            try:
                boost = await ctx.semantic_scorer.boost(
                    query_terms=query_terms,
                    candidate_text=haystack,
                )
                semantic_boosts[result.id] = boost
            except Exception:
                logger.exception(
                    "semantic_scorer.boost_failed", extra={"candidate_id": result.id}
                )

    re_ranked: list[SearchResult] = []
    for result in state.results:
        if not result.source_tool.startswith("search"):
            re_ranked.append(result)
            continue
        haystack = _evidence_haystack(result)
        score, hits = evidence_score(
            haystack,
            skills=skills,
            domains=domains,
            role=role,
            candidate_min_years=_candidate_min_years(result, haystack),
            required_min_years=required_years,
            domain_haystack=_domain_haystack(result),
            requested_name=requested_name or None,
            candidate_name=candidate_full_name(result) if requested_name else None,
            priority=priority,
        )
        # Semantic similarity boost — additive, capped at 1.0. Applied before
        # the enrichment tie-break so the semantic signal is part of the base
        # score rather than a separate post-processing step.
        if score > 0.0 and result.id in semantic_boosts:
            sem_boost = semantic_boosts[result.id] * ctx.semantic_boost_weight
            score = min(1.0, score + sem_boost)
        # Tiny tie-break for candidates enriched with a technical document or CV.
        if score > 0.0 and ENRICHMENT_TECH_DOC_KEY in result.data:
            score = min(1.0, score + 0.03)
        if score > 0.0 and ENRICHMENT_RESUME_KEY in result.data:
            resume_text = _resume_haystack(result)
            if resume_text:
                score = min(1.0, score + 0.02)
        is_full_match, unmet = _evaluate_match(
            hits,
            skills=skills,
            domains=domains,
            role=role,
            required_years=required_years,
            requested_name=requested_name or None,
        )
        re_ranked.append(
            result.model_copy(
                update={
                    "score": round(score, 4),
                    "is_full_match": is_full_match,
                    "unmet_criteria": unmet,
                }
            )
        )

    re_ranked.sort(key=lambda r: r.score, reverse=True)

    # Drop zero-score candidates when positive matches exist, then cap at 25.
    search_results = [r for r in re_ranked if r.source_tool.startswith("search")]
    other_results = [r for r in re_ranked if not r.source_tool.startswith("search")]
    positive = [r for r in search_results if r.score > 0.0]
    search_results = positive if positive else search_results
    re_ranked = search_results[:25] + other_results

    # Distinguish verified (in a technical document) / visible (in a summary
    # only) / missing, so the message never claims a criterion is unverifiable
    # when some candidate visibly shows it.
    missing, visible_only = _criteria_status(
        re_ranked,
        skills=skills,
        domains=domains,
        role=role,
        required_years=required_years,
    )
    warnings = list(state.warnings)
    if missing and not any(w.code == "criteria_unverified" for w in warnings):
        warnings.append(
            Warning(
                code="criteria_unverified",
                message="could not verify: " + ", ".join(missing),
            )
        )
    if visible_only and not any(w.code == "criteria_visible" for w in warnings):
        warnings.append(
            Warning(
                code="criteria_visible",
                message=(
                    "visible on candidate profiles but not confirmed in "
                    "technical documents: " + ", ".join(visible_only)
                ),
            )
        )

    logger.info(
        "graph.rank_candidates",
        extra={
            "skills": list(skills),
            "domains": list(domains),
            "role": role,
            "required_years": required_years,
            "missing_criteria": list(missing),
            "visible_unverified_criteria": list(visible_only),
            "ranked": [
                {"id": r.id, "source_tool": r.source_tool, "score": r.score}
                for r in re_ranked[:5]
            ],
        },
    )
    await _emit_candidate_cards_partial(ctx, re_ranked)
    return _replace(state, results=re_ranked, warnings=warnings)


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
    # On a reflection-triggered replan, the previous pass left guidance. Consume
    # it here and clear it immediately so it is used exactly once and the
    # bounded loop cannot spin. Only pass `feedback` when present, so planners
    # that don't accept it (e.g. simple test stubs) are unaffected on a first,
    # feedback-free pass.
    feedback = state.replan_feedback.strip()
    if feedback:
        state = _replace(state, replan_feedback="")
    plan_kwargs: dict[str, object] = dict(
        query=state.original_query,
        filters=dict(state.filters),
        tools=list(state.available_tools),
        constraints=constraints,
        emitter=ctx.event_emitter,
    )
    if feedback:
        plan_kwargs["feedback"] = feedback
    try:
        plan = await ctx.llm_planner.plan(**plan_kwargs)
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


# ---------------------------------------------------------------------------
# Value-level input guarding + Agent-API-owned dictionary resolution
# ---------------------------------------------------------------------------
#
# The LLM plans in a single pass and cannot know BoondManager dictionary
# ids, so it must NOT emit them. Two safety layers protect execution:
#   1. `_sanitize_tool_inputs` strips placeholder / wrongly-typed values
#      so a bad plan can never crash the MCP call (plan-validate checks
#      field names, not values).
#   2. `_resolve_search_filters` lets the Agent API resolve experience /
#      tool dictionary ids deterministically from the interpreted intent —
#      restoring the documented ownership boundary.

_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^\s*<.*>\s*$")
_ARRAY_OPERATOR_TOKENS: Final[frozenset[str]] = frozenset({"#AND#", "#OR#"})
_SEARCH_FILTER_TOOLS: Final[frozenset[str]] = frozenset(
    {SEARCH_CANDIDATES_TOOL, LEGACY_CONSULTANT_SEARCH_TOOL}
)
# searchCandidates fields that carry an experience-level filter, real
# schema first (the live tool exposes the plural `experiences`).
_SEARCH_EXPERIENCE_FIELDS: Final[tuple[str, ...]] = (
    "experiences",
    "experience",
    "experienceLevel",
    "experience_id",
)
_SEARCH_TOOLS_FIELD: Final[str] = "tools"


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def _schema_field_spec(schema: dict[str, object], field: str) -> dict[str, object]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        spec = properties.get(field)
        if isinstance(spec, dict):
            return spec
    return {}


def _array_item_type(spec: dict[str, object]) -> str | None:
    if spec.get("type") != "array":
        return None
    items = spec.get("items")
    if isinstance(items, dict):
        item_type = items.get("type")
        return item_type if isinstance(item_type, str) else None
    return None


def _int_coercible(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        try:
            int(value.strip())
        except ValueError:
            return False
        return True
    return False


def _sanitize_tool_inputs(
    inputs: dict[str, object], schema: dict[str, object]
) -> tuple[dict[str, object], list[str]]:
    """Strip input values that could never execute against the MCP schema.

    Returns the cleaned inputs plus the names of dropped fields. Guards:
    - placeholder scalars / list elements (e.g. ``"<JAVA_ID>"``),
    - non-integer values in an integer-typed field or array,
    - arrays that collapse to nothing meaningful (only operator tokens).
    """
    clean: dict[str, object] = {}
    dropped: list[str] = []
    for key, value in inputs.items():
        spec = _schema_field_spec(schema, str(key))

        if isinstance(value, list):
            item_type = _array_item_type(spec)
            cleaned_items: list[object] = []
            for item in value:
                if _is_placeholder(item):
                    continue
                if isinstance(item, str) and item in _ARRAY_OPERATOR_TOKENS:
                    cleaned_items.append(item)
                    continue
                if item_type == "integer" and not _int_coercible(item):
                    continue
                cleaned_items.append(item)
            meaningful = [
                it
                for it in cleaned_items
                if not (isinstance(it, str) and it in _ARRAY_OPERATOR_TOKENS)
            ]
            if not meaningful:
                dropped.append(str(key))
                continue
            clean[key] = cleaned_items
            continue

        if _is_placeholder(value):
            dropped.append(str(key))
            continue
        if spec.get("type") == "integer" and not _int_coercible(value):
            dropped.append(str(key))
            continue
        clean[key] = value
    return clean, dropped


def _coerce_scalar(value: object, target_type: object) -> object:
    if target_type == "integer" and _int_coercible(value):
        return int(str(value).strip())
    if target_type == "string":
        return str(value)
    return value


def _coerce_for_field(
    schema: dict[str, object], field: str, value: object
) -> object:
    spec = _schema_field_spec(schema, field)
    if spec.get("type") == "array":
        return [_coerce_scalar(value, _array_item_type(spec))]
    return _coerce_scalar(value, spec.get("type"))


def _coerce_array_for_field(
    schema: dict[str, object], field: str, values: list[object]
) -> list[object]:
    spec = _schema_field_spec(schema, field)
    item_type: object = (
        _array_item_type(spec)
        if spec.get("type") == "array"
        else spec.get("type")
    )
    out: list[object] = []
    for value in values:
        if item_type == "integer" and not _int_coercible(value):
            continue
        out.append(_coerce_scalar(value, item_type))
    return out


async def _fetch_dictionary(
    ctx: NodeContext, available_by_name: dict[str, McpTool]
) -> list[dict[str, object]] | None:
    """Fetch the BoondManager reference dictionary, or None if unavailable.

    The live ``getDictionary`` takes no inputs; we still try a couple of
    legacy key-param shapes for mock/older servers. Never raises.
    """
    dict_tool = available_by_name.get(DICTIONARY_TOOL)
    if dict_tool is None:
        return None
    attempt_args: list[dict[str, object]] = [{}]
    dict_properties = _schema_property_names(dict_tool.input_schema)
    for param in _DICTIONARY_KEY_PARAMS:
        if param in dict_properties:
            attempt_args.append({param: "setting"})
    for args in attempt_args:
        try:
            raw = await ctx.mcp_client.call_tool(DICTIONARY_TOOL, args)
        except (McpTransientError, McpToolError):
            logger.warning("graph.llm_dictionary_call_failed", extra={"args": args})
            continue
        if raw:
            return [r for r in raw if isinstance(r, dict)]
    return None


async def _resolve_search_filters(
    ctx: NodeContext,
    inputs: dict[str, object],
    schema: dict[str, object],
    intent: InterpretedIntent | None,
    available_by_name: dict[str, McpTool],
) -> tuple[dict[str, object], list[Warning]]:
    """Inject Agent-API-resolved dictionary filters into search inputs.

    The LLM only declares intent; the Agent API resolves experience/tool
    dictionary ids here (best-effort, never inventing an id). Filters the
    (sanitized) plan already supplied validly are left untouched.
    """
    warnings: list[Warning] = []
    if intent is None:
        return inputs, warnings

    property_names = _schema_property_names(schema)
    min_years_raw = intent.constraints.get("min_experience_years")

    exp_field = next(
        (f for f in _SEARCH_EXPERIENCE_FIELDS if f in property_names), None
    )
    # Only the experience-level filter is injected here. The structured
    # `tools` id filter is intentionally NOT applied — it is unreliable and
    # can kill recall; skill matching is handled by keywords + ranking.
    needs_experience = bool(min_years_raw) and exp_field is not None and (
        exp_field not in inputs
    )
    if not needs_experience or exp_field is None:
        return inputs, warnings

    raw = await _fetch_dictionary(ctx, available_by_name)
    if raw is None:
        warnings.append(_experience_unmapped_warning())
        return inputs, warnings

    min_years = _int_or_none(min_years_raw)
    entry_id = (
        resolve_experience_id(
            dictionary_section_entries(raw, "experience"), min_years
        )
        if min_years is not None
        else None
    )
    if entry_id is None:
        warnings.append(_experience_unmapped_warning())
        return inputs, warnings

    resolved = dict(inputs)
    resolved[exp_field] = _coerce_for_field(schema, exp_field, entry_id)
    return resolved, warnings


def _experience_unmapped_warning() -> Warning:
    return Warning(
        code="experience_filter_unmapped",
        message=(
            "Years-of-experience filter is not applied: no matching "
            "dictionary entry was found for the requested experience level."
        ),
    )


_MAX_SEARCH_PASSES: Final[int] = 5

def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _candidate_min_years(result: SearchResult, haystack: str) -> int | None:
    """Best-known minimum years for a candidate.

    Prefers the MCP-resolved ``experienceMinYears``; falls back to a years
    figure parsed from the candidate's CV free-text.
    """
    resolved = _record_experience_min_years(result)
    parsed = parse_years(haystack)
    known = [y for y in (resolved, parsed) if y is not None]
    return max(known) if known else None


def _prerank_search_results(
    results: list[SearchResult],
    *,
    anchors_skills: tuple[str, ...],
    anchors_domains: tuple[str, ...],
    anchors_role: str | None,
    required_years: int | None,
    requested_name: str | None = None,
    priority: tuple[str, ...] | None = None,
) -> None:
    """Reorder search summaries by visible evidence.

    Enrichment is bounded, so it must spend its budget on the candidates
    whose SUMMARY already shows the most evidence (skill/role/domain/
    seniority/name) — not the first N in BoondManager order. Seniority comes
    from the MCP-resolved ``experienceMinYears`` on each summary. Mutates
    ``results`` in place so the downstream fan-out picks the best candidates.
    Uses the same name/primary signals as final ranking so a named person is
    enriched, not dropped beyond the budget.
    """
    annotated = list(results)

    def _key(result: SearchResult) -> float:
        if not result.source_tool.startswith("search"):
            return -1.0
        haystack = _evidence_haystack(result)
        score, _ = evidence_score(
            haystack,
            skills=anchors_skills,
            domains=anchors_domains,
            role=anchors_role,
            candidate_min_years=_candidate_min_years(result, haystack),
            required_min_years=required_years,
            domain_haystack=_domain_haystack(result),
            requested_name=requested_name or None,
            candidate_name=candidate_full_name(result) if requested_name else None,
            priority=priority,
        )
        return score

    annotated.sort(key=_key, reverse=True)
    results[:] = annotated


async def _execute_search_ladder(
    ctx: NodeContext,
    *,
    tool: McpTool,
    intent: InterpretedIntent | None,
    available_by_name: dict[str, McpTool],
    tool_calls: list[ToolCall],
    results: list[SearchResult],
    warnings: list[Warning],
    errors: list[AgentError],
) -> bool:
    """Run searchCandidates as a recall-first relaxation ladder.

    ``searchCandidates`` is a recall tool, so instead of one strict call we
    build a bounded ladder of progressively broader passes from the
    interpreted intent (generic anchors — no hardcoded skill) and stop at
    the first pass that returns candidates. Returns ``True`` when the ladder
    handled the search; ``False`` when no usable anchors exist (the caller
    then falls back to the planned search inputs).
    """
    if intent is None:
        return False

    schema = tool.input_schema
    property_names = _schema_property_names(schema)
    entities = [str(e).strip() for e in intent.entities if str(e).strip()]
    if not entities and not intent.constraints:
        return False

    raw = await _fetch_dictionary(ctx, available_by_name)
    tool_entries = dictionary_section_entries(raw, "tool") if raw else []

    # An entity is a concrete (server-filterable) skill iff it resolves to a
    # tool dictionary id. This is generic across technologies.
    skill_labels = {
        e.lower() for e in entities if tool_entries and resolve_tool_ids(tool_entries, [e])
    }
    # A named person is the strongest anchor: search by name first, rank the
    # other criteria within the matches.
    name = (intent.constraints.get("name") or "").strip()
    anchors = classify_anchors(
        intent.entities, intent.constraints, skill_labels, name=name or None
    )
    if anchors.is_empty():
        return False

    # Keyword-only recall ladder: the structured `tools` filter is unreliable
    # (it kills recall), so precision comes from evidence pre-ranking and
    # ranking, not from hard id filters on the search.
    passes = build_recall_passes(
        anchors, schema_fields=property_names, max_passes=_MAX_SEARCH_PASSES
    )
    if not passes:
        return False

    required_years = _int_or_none(intent.constraints.get("min_experience_years"))

    start_len = len(tool_calls)
    used_relaxed: bool | None = None
    matched_label: str | None = None
    for index, search_pass in enumerate(passes):
        if index > 0:
            await ctx.event_emitter.emit(
                "search_relaxed",
                {
                    "reason": "previous search returned no candidates",
                    "next_pass": search_pass.label,
                    "pass_index": index,
                },
            )
        inputs, _dropped = _sanitize_tool_inputs(dict(search_pass.inputs), schema)
        call, raw_records = await _execute_single_tool(ctx, tool.name, inputs)
        tool_calls.append(call)
        if call.status is ToolCallStatus.FAILED:
            _absorb_direct_outcome(
                call, raw_records, tool.name, results, warnings, errors
            )
            return True
        if raw_records:
            _absorb_direct_outcome(
                call, raw_records, tool.name, results, warnings, errors
            )
            used_relaxed = search_pass.relaxed
            matched_label = search_pass.label
            # Always complement with a titleSkills pass so candidates whose
            # profile title matches (e.g. "Tech Lead Java backend") are included
            # even when the resumeTd pass already returned results.
            if search_pass.inputs.get("keywordsType") != "titleSkills":
                title_inputs, _ = _sanitize_tool_inputs(
                    {**search_pass.inputs, "keywordsType": "titleSkills"}, schema
                )
                title_call, title_records = await _execute_single_tool(
                    ctx, tool.name, title_inputs
                )
                tool_calls.append(title_call)
                if title_call.status is ToolCallStatus.SUCCESS and title_records:
                    _absorb_direct_outcome(
                        title_call, title_records, tool.name, results, warnings, errors
                    )
            break

    # A named-person query that was NOT satisfied by the dedicated name pass
    # means we couldn't find that person and fell through to the criteria
    # ladder — surface that honestly instead of silently returning look-alikes.
    name_missed = bool(anchors.name) and matched_label != "name"

    if used_relaxed is not None:
        # Found candidates — pre-rank summaries so the best (by visible
        # evidence), not the first N, are the ones enriched downstream.
        _prerank_search_results(
            results,
            anchors_skills=anchors.skills,
            anchors_domains=anchors.domains,
            anchors_role=anchors.role,
            required_years=required_years,
            requested_name=anchors.name,
            priority=_ranking_priority(intent.constraints),
        )
        if name_missed:
            warnings.append(
                Warning(
                    code="name_not_found",
                    message=(
                        f"No candidate matching the name '{anchors.name}' was "
                        "found; showing candidates matching the other criteria "
                        "instead."
                    ),
                )
            )
        elif used_relaxed:
            warnings.append(
                Warning(
                    code="search_broadened",
                    message=(
                        "The initial search was broadened to find candidates; "
                        "some criteria may not be strictly applied."
                    ),
                )
            )
    else:
        # Every pass ran successfully but returned nothing.
        any_failure = any(
            c.status is ToolCallStatus.FAILED for c in tool_calls[start_len:]
        )
        if not any_failure:
            if anchors.name:
                warnings.append(
                    Warning(
                        code="name_not_found",
                        message=(
                            f"No candidate matching the name '{anchors.name}' "
                            "was found, and no candidates matched the other "
                            "criteria either."
                        ),
                    )
                )
            else:
                warnings.append(
                    Warning(
                        code="no_results_after_fallback",
                        message=(
                            "No candidates were found, even after broader "
                            "fallback searches."
                        ),
                    )
                )
    return True


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
            # searchCandidates is recall-first: let the Agent API run a
            # bounded relaxation ladder built from the interpreted intent.
            # Falls back to the planned inputs when no anchors are usable.
            if step.tool_name in _SEARCH_FILTER_TOOLS:
                handled = await _execute_search_ladder(
                    ctx,
                    tool=tool,
                    intent=state.interpreted_intent,
                    available_by_name=available_by_name,
                    tool_calls=tool_calls,
                    results=results,
                    warnings=warnings,
                    errors=errors,
                )
                if handled:
                    continue
            inputs = dict(step.inputs)
            inputs, dropped = _sanitize_tool_inputs(inputs, tool.input_schema)
            if dropped:
                warnings.append(
                    Warning(
                        code="filter_unresolved",
                        message=(
                            "Some planned filters were dropped because they "
                            "could not be resolved or were wrongly typed: "
                            + ", ".join(sorted(set(dropped)))
                            + "."
                        ),
                    )
                )
            if step.tool_name in _SEARCH_FILTER_TOOLS:
                inputs, resolve_warnings = await _resolve_search_filters(
                    ctx,
                    inputs,
                    tool.input_schema,
                    state.interpreted_intent,
                    available_by_name,
                )
                warnings.extend(resolve_warnings)
            call, raw = await _execute_single_tool(ctx, step.tool_name, inputs)
            tool_calls.append(call)
            _absorb_direct_outcome(
                call, raw, step.tool_name, results, warnings, errors
            )
            continue

        # getCandidateDetail carries no skills/experience/work-history, so
        # it is useless for criteria verification. Skip it as a fan-out
        # enrichment to preserve the budget for the technical document (the
        # actual evidence tool). The direct candidate-detail-by-id flow is
        # not a fan-out and is unaffected.
        if step.tool_name == CANDIDATE_DETAIL_TOOL:
            logger.info(
                "graph.skip_detail_fanout",
                extra={"depends_on": step.depends_on},
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
            # Guard against placeholder / wrongly-typed extras the LLM may
            # have layered on; the fan-out key itself is always clean.
            inputs, _dropped = _sanitize_tool_inputs(inputs, tool.input_schema)
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
