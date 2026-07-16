"""LLM-based MCP tool planner.

This module is the **primary** real-mode planner: it asks an LLM to
interpret the user's query against the discovered MCP tool catalogue
and emit a strictly-validated, bounded execution plan.

Design rules (enforced here, not in the workflow):

- No free-form tool execution semantics in the LLM output.
- No unknown tool names. No schema-violating inputs.
- No unbounded plans (caller supplies ``max_steps``).
- No silent fallbacks: validation failures raise ``LlmPlannerError``;
  callers decide whether to surface them as warnings or fail.

The LLM call itself is injected via ``ChatFn`` so production wires up
the Anthropic SDK while tests pass a stub that returns a canned JSON
plan — no network access required.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.intent import LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool
from app.services.event_emitter import EventEmitter, NoopEventEmitter

logger = logging.getLogger(__name__)


class LlmPlannerError(RuntimeError):
    """Raised when LLM planning produces no usable plan."""


@dataclass(frozen=True)
class PlannerConstraints:
    """Caller-provided bounds the LLM must respect."""

    max_plan_steps: int = 6
    max_enrichments: int = 5

    def as_dict(self) -> dict[str, object]:
        return {
            "max_plan_steps": self.max_plan_steps,
            "max_enrichments": self.max_enrichments,
        }


ChatFn = Callable[[str, str], Awaitable[str]]
"""(system_prompt, user_prompt) -> raw LLM text response."""


class LlmPlanner(Protocol):
    """Async planner contract.

    Implementations must return a *validated* ``LlmToolPlan`` or raise
    ``LlmPlannerError``. The workflow never calls into an LLM directly.

    The optional ``emitter`` lets implementations stream
    ``plan_created`` (raw LLM plan) and ``plan_validated`` (after the
    strict validator) events to a streaming-mode consumer. Non-streaming
    callers can omit it.
    """

    async def plan(
        self,
        *,
        query: str,
        filters: dict[str, object],
        tools: list[McpTool],
        constraints: PlannerConstraints,
        emitter: EventEmitter | None = None,
        feedback: str = "",
    ) -> LlmToolPlan: ...

    async def reflect(
        self,
        *,
        query: str,
        results_summary: str,
        emitter: EventEmitter | None = None,
    ) -> "ReflectionVerdict":
        """Judge ranked results; decide whether a guided replan is warranted.

        Optional: implementations that don't support reflection (e.g. test
        stubs) may omit it — the workflow guards with ``getattr`` and treats a
        missing ``reflect`` as 'never replan'.
        """
        ...


_RESULT_SELECTOR_ALLOWED: Final[frozenset[str]] = frozenset({"candidate_ids"})

# Tools that may use ``result_selector="candidate_ids"`` to fan out
# over a previous search's candidate ids. Other tools (e.g.
# ``searchCandidates``, ``getDictionary``) MUST NOT request that
# selector — it makes no semantic sense for them.
_FANOUT_ELIGIBLE_TOOLS: Final[frozenset[str]] = frozenset(
    {"getCandidateDetail", "getCandidateTechnicalDocument"}
)


def _schema_property_names(schema: dict[str, object]) -> set[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return set()
    return {str(name) for name in properties.keys()}


def _required_property_names(schema: dict[str, object]) -> set[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {str(name) for name in required if isinstance(name, str)}


@dataclass(frozen=True)
class PlanValidationResult:
    """Validator output retaining both accepted and rejected steps.

    Used by the streaming path so the ``plan_validated`` event can
    surface what the validator dropped (and why).
    """

    accepted: LlmToolPlan
    rejected: list[dict[str, str]]


def validate_plan_with_diagnostics(
    raw_plan: LlmToolPlan,
    tools: list[McpTool],
    constraints: PlannerConstraints,
) -> PlanValidationResult:
    """Validate the LLM plan, returning accepted steps + rejection reasons.

    Never raises — the caller decides whether an empty ``accepted.plan``
    is fatal (``validate_plan`` enforces that policy for non-streaming
    callers).
    """
    if len(raw_plan.plan) > constraints.max_plan_steps:
        logger.warning(
            "llm_planner.plan_truncated",
            extra={
                "original_steps": len(raw_plan.plan),
                "max_steps": constraints.max_plan_steps,
            },
        )

    tools_by_name = {tool.name: tool for tool in tools}

    validated_steps: list[PlannedToolCall] = []
    rejected: list[dict[str, str]] = []
    completed_tools: set[str] = set()

    for step in raw_plan.plan[: constraints.max_plan_steps]:
        error = _validate_step(step, tools_by_name, completed_tools)
        if error is not None:
            rejected.append({"tool": step.tool_name, "reason": error})
            continue
        validated_steps.append(step)
        completed_tools.add(step.tool_name)

    if rejected:
        logger.warning("llm_planner.steps_rejected", extra={"rejected": rejected})

    accepted = raw_plan.model_copy(update={"plan": validated_steps})
    return PlanValidationResult(accepted=accepted, rejected=rejected)


def validate_plan(
    raw_plan: LlmToolPlan,
    tools: list[McpTool],
    constraints: PlannerConstraints,
) -> LlmToolPlan:
    """Validate every planned step against the discovered MCP catalogue.

    Drops invalid steps and returns the validated remainder. If nothing
    survives, raises ``LlmPlannerError`` so the workflow can surface a
    clean failure instead of pretending to act.
    """
    result = validate_plan_with_diagnostics(raw_plan, tools, constraints)
    if not result.accepted.plan:
        raise LlmPlannerError(
            "LLM produced no valid plan steps "
            f"(rejected={len(result.rejected)}, original={len(raw_plan.plan)})"
        )
    return result.accepted


def _validate_step(
    step: PlannedToolCall,
    tools_by_name: dict[str, McpTool],
    completed_tools: set[str],
) -> str | None:
    tool = tools_by_name.get(step.tool_name)
    if tool is None:
        return f"unknown tool {step.tool_name!r}"

    allowed_properties = _schema_property_names(tool.input_schema)
    if allowed_properties:
        for key in step.inputs:
            if key not in allowed_properties:
                return (
                    f"input {key!r} is not declared in {step.tool_name} "
                    "input_schema"
                )

    if step.depends_on is not None:
        if step.depends_on not in completed_tools:
            return (
                f"depends_on {step.depends_on!r} does not refer to an "
                "earlier validated step"
            )
        if (
            step.result_selector is not None
            and step.result_selector not in _RESULT_SELECTOR_ALLOWED
        ):
            return f"unsupported result_selector {step.result_selector!r}"
        # `candidate_ids` is only meaningful for candidate enrichment
        # tools; allowing it on, say, ``searchCandidates`` would let the
        # LLM accidentally request fan-out where a direct call was meant.
        if (
            step.result_selector == "candidate_ids"
            and step.tool_name not in _FANOUT_ELIGIBLE_TOOLS
        ):
            return (
                f"result_selector='candidate_ids' is only allowed on "
                f"candidate-enrichment tools, not {step.tool_name!r}"
            )
        # A depends_on with no selector is an ordering hint only; if
        # the tool has required schema fields, they must be supplied
        # by the LLM (the executor will not invent them).
        if step.result_selector is None:
            required = _required_property_names(tool.input_schema)
            missing = required - set(step.inputs.keys())
            if missing:
                return (
                    f"required input(s) {sorted(missing)} missing for "
                    f"{step.tool_name}"
                )
    else:
        # Without dependency-fill, required schema fields must be present.
        required = _required_property_names(tool.input_schema)
        missing = required - set(step.inputs.keys())
        if missing:
            return (
                f"required input(s) {sorted(missing)} missing for "
                f"{step.tool_name}"
            )

    return None


def build_planner_prompt(
    *,
    query: str,
    filters: dict[str, object],
    tools: list[McpTool],
    constraints: PlannerConstraints,
    role: str = "",
    feedback: str = "",
    current_date: date | None = None,
) -> tuple[str, str]:
    """Build the (system_prompt, user_prompt) pair sent to the LLM.

    ``role`` is an optional, operator-configurable persona preamble. It is
    prepended for framing only — the mechanical rules and JSON output schema
    below are fixed and always applied. With ``role=""`` the system prompt is
    identical to the rules-only prompt.

    ``feedback`` is optional guidance from a prior reflection pass (the LLM
    decided the first results were inadequate). When set, it is added to the
    user prompt so this re-plan changes its approach. With ``feedback=""`` the
    user prompt is identical to a first-pass prompt.

    ``current_date`` (defaults to today) is stated in the user prompt so the
    LLM can convert date-anchored criteria — e.g. a graduation window
    ('diplômé entre 2010 et 2020') — into experience-year bounds; injectable
    for deterministic tests.
    """
    persona = f"{role.strip()}\n\n" if role and role.strip() else ""
    system = (
        f"{persona}"
        "You are the planning component of an MCP-backed candidate search "
        "agent. You receive a user query and a catalogue of available MCP "
        "tools. You must return a JSON object matching the schema below, "
        "and nothing else (no prose, no markdown fences).\n\n"
        "RULES (must be obeyed):\n"
        "1. Use only tools whose name appears in the provided catalogue.\n"
        "2. Use only input fields declared in each tool's input_schema.\n"
        "3. Required schema fields must be present unless `depends_on` "
        "fills them from a previous tool's results.\n"
        "4. Do NOT emit dictionary IDs, placeholder tokens (e.g. `<...>`), "
        "or ID-based filters (such as `experiences` or `tools`) whose ids "
        "you do not already have. You plan in a SINGLE pass and will NOT "
        "see getDictionary's output, so you cannot know dictionary ids. "
        "Declare the criteria in `interpreted_intent` instead — the Agent "
        "API resolves experience/tool dictionary filters itself. For "
        "free-text narrowing you may set `keywords` (and `keywordsType`), "
        "which need no dictionary ids.\n"
        "5. Never propose a tool call that targets a system outside MCP.\n"
        "6. Plan must contain at most max_plan_steps entries.\n"
        "7. `searchCandidates` is a RECALL tool, not a strict filter. The "
        "Agent API builds and reactively broadens the actual search from "
        "your `interpreted_intent`, so do NOT cram every criterion into one "
        "search, and NEVER use boolean `OR`/`AND` or parentheses in "
        "`keywords` (only `+term` / \"exact phrase\" are supported). A "
        "single searchCandidates step is enough.\n"
        "8. For deeper criteria (skills depth, seniority, domain/last "
        "experience), enrich with `getCandidateTechnicalDocument` via "
        "`depends_on` + `result_selector='candidate_ids'` (the technical "
        "document is the evidence source). Do NOT use `getCandidateDetail` "
        "for criteria — it only holds contact/admin data.\n"
        "9. Use `depends_on` + `result_selector='candidate_ids'` ONLY for "
        "per-candidate enrichment that runs once per candidate id returned "
        "by the named earlier search step. To say 'run B after A with "
        "explicit inputs', leave BOTH `depends_on` and `result_selector` "
        "null (steps already execute in plan order).\n"
        "10. In `interpreted_intent`, populate `entities` with ONLY concrete "
        "skills/technologies, each a single concept (e.g. \"java\", "
        "\"spring\", \"aws\", \"kubernetes\"). Do NOT put roles, seniority, "
        "years, or multi-word business phrases in `entities`. Put the "
        "structured criteria in `constraints` instead: `role` (e.g. "
        "developer, business analyst, project manager), `domain` or "
        "`last_experience_company` for the business sector/company/acronym "
        "(e.g. banking, payments, \"CIB (Corporate & Investment Banking)\"), "
        "and the experience bounds `min_experience_years` and "
        "`max_experience_years`. For a RANGE ('0-2 ans', '3 to 5 years') set "
        "both bounds. For a CAP ('junior', 'moins de 3 ans', 'up to 2 years') "
        "set `max_experience_years` (junior ⇒ 2; do not also set a min). For a "
        "FLOOR ('senior', '5+ years', 'au moins 5 ans') set "
        "`min_experience_years` (senior ⇒ 5). If the user anchors seniority to "
        "a GRADUATION/degree period ('diplômé entre 2010 et 2020', 'graduated "
        "in 2015'), convert it to experience bounds using the current date "
        "given in the user message: min_experience_years = current_year − "
        "LATEST graduation year, max_experience_years = current_year − "
        "EARLIEST graduation year (a single graduation year sets both bounds "
        "from that year). Never put graduation years in `entities` or "
        "`keywords`. Keep the user's original acronym/term "
        "verbatim in `domain`. These drive Agent-API-side recall, filter "
        "resolution, and honest scoring/messaging; do not omit a criterion "
        "you understood. IMPORTANT: always normalise skill/technology names "
        "to their canonical English form (e.g. 'JS' → 'javascript', 'K8s' → "
        "'kubernetes', 'TS' → 'typescript', 'ML' → 'machine learning', "
        "'IA' → 'artificial intelligence', 'Py' → 'python', 'Node' → "
        "'node.js'). If the query is in French, translate technical skill "
        "terms to English before placing them in `entities` (e.g. "
        "'apprentissage automatique' → 'machine learning', 'nuage' → 'cloud', "
        "'conteneurs' → 'docker'). Role and domain terms may stay in the "
        "language the user used.\n"
        "11. If the user identifies a SPECIFIC PERSON by name (e.g. \"named "
        "X\", \"whose name is X\", \"called X\", or a bare proper name), put "
        "that full name verbatim in `constraints.name`. Keep skills/role/"
        "domain in their usual places. The Agent API searches by that name "
        "FIRST and ranks the other criteria within the name matches, so do "
        "NOT cram the name into `entities` or `keywords`.\n"
        "12. Optionally set `constraints.ranking_priority` to a comma-separated, "
        "MOST-IMPORTANT-FIRST ordering of the criteria that matter for this "
        "query — any of: name, skill, domain, role, seniority. List every "
        "criterion the user implies, ordered by importance (e.g. a specific "
        "\"last job in CIB\" and an explicit role outrank a generic seniority "
        "floor); put `name` first when a specific person is named. Omit it when "
        "the user gives no sense of relative importance (the Agent API then uses "
        "its default weights). This only re-weights Agent-API ranking; it never "
        "changes which records are fetched.\n\n"
        "OUTPUT SCHEMA (return JSON object with these keys exactly):\n"
        "{\n"
        '  "interpreted_intent": {"entities": ["..."], "constraints": {"...": "...", "name": "Full Name (only when a person is named)", "ranking_priority": "domain,role,skill,seniority (optional, ordered most-important-first)"}},\n'
        '  "plan": [\n'
        "    {\n"
        '      "tool_name": "...",\n'
        '      "reason": "...",\n'
        '      "inputs": {...},\n'
        '      "depends_on": "tool_name or null",\n'
        '      "result_selector": "candidate_ids or null"\n'
        "    }\n"
        "  ],\n"
        '  "assumptions": ["..."],\n'
        '  "warnings": ["..."]\n'
        "}"
    )

    tool_lines: list[str] = []
    for tool in tools:
        tool_lines.append(
            "- name: " + tool.name
            + "\n  description: " + (tool.description or "")
            + "\n  input_schema: " + json.dumps(tool.input_schema)
        )
    tool_block = "\n".join(tool_lines) if tool_lines else "(none)"

    feedback_block = ""
    if feedback and feedback.strip():
        feedback_block = (
            "PREVIOUS ATTEMPT — the last search was judged inadequate. "
            "Incorporate this guidance and change your approach (e.g. adjust "
            "keywords, `ranking_priority`, or broaden/drop a constraint):\n"
            f"{feedback.strip()}\n\n"
        )
    today = current_date if current_date is not None else date.today()
    user = (
        f"Current date: {today.isoformat()}\n"
        f"User query: {query!r}\n"
        f"User filters (raw): {json.dumps(filters, default=str)}\n"
        f"Execution constraints: {json.dumps(constraints.as_dict())}\n\n"
        f"{feedback_block}"
        f"Available MCP tools:\n{tool_block}\n\n"
        "Produce the JSON plan now."
    )
    return system, user


def parse_plan_response(text: str) -> LlmToolPlan:
    """Parse the LLM's text response into an LlmToolPlan.

    Tolerant of a single Markdown code fence around the JSON since that
    is the most common LLM defection from "JSON only".
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove the opening fence (with or without language tag) and the
        # closing fence.
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -3]
    stripped = stripped.strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LlmPlannerError(f"LLM returned non-JSON output: {exc}") from exc

    if not isinstance(payload, dict):
        raise LlmPlannerError(
            "LLM JSON output must be an object at the top level"
        )

    try:
        return LlmToolPlan.model_validate(payload)
    except ValidationError as exc:
        raise LlmPlannerError(f"LLM JSON failed schema validation: {exc}") from exc


class ReflectionVerdict(BaseModel):
    """LLM judgement: accept the results, replan a search, or ask the user."""

    model_config = ConfigDict(extra="ignore")

    needs_replan: bool = Field(default=False)
    reason: str = Field(default="")
    guidance: str = Field(default="")
    # Clarification path: ask the user instead of (or before) replanning.
    needs_clarification: bool = Field(default=False)
    clarification_question: str = Field(default="")
    clarification_fields: list[str] = Field(default_factory=list)


def build_reflection_prompt(
    *,
    role: str,
    query: str,
    results_summary: str,
    criteria_summary: str = "",
) -> tuple[str, str]:
    """Build the (system, user) prompt for the post-ranking reflection.

    The reflection judges whether the ranked candidates adequately answer the
    query and, if not, what the next (single, guided) search pass should change.
    Reuses the configurable persona. Output is a small fixed JSON verdict.
    """
    persona = f"{role.strip()}\n\n" if role and role.strip() else ""
    system = (
        f"{persona}"
        "You are reviewing the ranked candidates a search just produced and "
        "choosing ONE of three outcomes: ACCEPT the results, RETRY one more "
        "better-targeted search, or ASK THE USER to clarify. "
        "Return a JSON object and nothing else (no prose, no markdown fences) "
        "with exactly these keys:\n"
        '{"needs_replan": true|false, "guidance": "...", '
        '"needs_clarification": true|false, "clarification_question": "...", '
        '"clarification_fields": ["..."], "reason": "..."}\n\n'
        "RULES:\n"
        "1. ACCEPT (all false) when the results are already a reasonable answer.\n"
        "2. RETRY (`needs_replan` true) ONLY if another search would plausibly "
        "find materially better candidates (top results miss the core "
        "requirement, or too few real matches). `guidance` MUST be a short, "
        "concrete instruction for the next plan (keywords, ranking_priority, "
        "broaden/drop a constraint). Do not restate the query verbatim.\n"
        "3. ASK (`needs_clarification` true) when a RETRY would NOT help without "
        "more information — ESPECIALLY when a query PARAMETER could not be "
        "resolved or is ambiguous (an unrecognised technology/skill, an unknown "
        "location or company, contradictory criteria, or a query too vague to "
        "target). `clarification_question` MUST be one short, friendly question "
        "naming exactly what you need; `clarification_fields` lists 1-3 short "
        "machine field names (e.g. [\"skill\", \"location\"]).\n"
        "4. Pick AT MOST ONE of retry/ask. Prefer ASK over RETRY when the "
        "problem is an unresolved/ambiguous parameter; prefer ACCEPT when "
        "unsure (do not pester the user needlessly).\n"
        "5. Judge only from the evidence shown; never invent candidate facts."
    )
    criteria = f"\nInterpreted criteria & resolution notes:\n{criteria_summary}\n" if criteria_summary else ""
    user = (
        f"User query: {query!r}\n"
        f"{criteria}"
        f"\nCurrent ranked candidates (top results):\n{results_summary}\n\n"
        "Return the JSON verdict now."
    )
    return system, user


def parse_reflection_response(text: str) -> ReflectionVerdict:
    """Parse the LLM reflection text into a ``ReflectionVerdict``.

    Tolerant of a single Markdown code fence. On any parse/validation failure
    returns a safe ``needs_replan=False`` verdict (fail-safe: never loop on a
    malformed reflection).
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    stripped = stripped.strip()
    try:
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            return ReflectionVerdict()
        return ReflectionVerdict.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return ReflectionVerdict()


def serialize_planned_steps(
    plan: list[PlannedToolCall],
) -> list[dict[str, object]]:
    """Render planned steps for UI events (safe scalar payload only)."""
    rendered: list[dict[str, object]] = []
    for index, step in enumerate(plan, start=1):
        rendered.append(
            {
                "step": index,
                "tool_name": step.tool_name,
                "reason": step.reason,
                "inputs": dict(step.inputs),
                "depends_on": step.depends_on,
                "result_selector": step.result_selector,
            }
        )
    return rendered


class StructuredLlmPlanner(LlmPlanner):
    """Default ``LlmPlanner`` implementation.

    Composes a prompt, calls the injected ``ChatFn``, parses + validates
    the JSON response into a bounded ``LlmToolPlan``. Knows nothing
    about HTTP, SDKs, or BoondManager.

    When an ``EventEmitter`` is supplied, emits:
    - ``plan_created`` once the raw LLM response has been parsed.
    - ``plan_validated`` once the validator has dropped any bad steps.
    """

    def __init__(self, chat_fn: ChatFn, *, role: str = "") -> None:
        self._chat_fn = chat_fn
        self._role = role

    async def plan(
        self,
        *,
        query: str,
        filters: dict[str, object],
        tools: list[McpTool],
        constraints: PlannerConstraints,
        emitter: EventEmitter | None = None,
        feedback: str = "",
    ) -> LlmToolPlan:
        sink = emitter or NoopEventEmitter()
        system, user = build_planner_prompt(
            query=query,
            filters=filters,
            tools=tools,
            constraints=constraints,
            role=self._role,
            feedback=feedback,
        )
        logger.info(
            "llm_planner.request",
            extra={
                "query": query,
                "available_tool_count": len(tools),
                "max_plan_steps": constraints.max_plan_steps,
            },
        )
        raw_text = await self._chat_fn(system, user)
        raw_plan = parse_plan_response(raw_text)

        await sink.emit(
            "plan_created",
            {
                "plan": serialize_planned_steps(raw_plan.plan),
                "assumptions": list(raw_plan.assumptions),
                "warnings": list(raw_plan.warnings),
            },
        )

        validation = validate_plan_with_diagnostics(raw_plan, tools, constraints)
        await sink.emit(
            "plan_validated",
            {
                "accepted_steps": serialize_planned_steps(validation.accepted.plan),
                "rejected_steps": list(validation.rejected),
            },
        )
        if not validation.accepted.plan:
            raise LlmPlannerError(
                "LLM produced no valid plan steps "
                f"(rejected={len(validation.rejected)}, "
                f"original={len(raw_plan.plan)})"
            )

        logger.info(
            "llm_planner.plan_validated",
            extra={
                "plan_step_count": len(validation.accepted.plan),
                "tools": [step.tool_name for step in validation.accepted.plan],
            },
        )
        return validation.accepted

    async def reflect(
        self,
        *,
        query: str,
        results_summary: str,
        criteria_summary: str = "",
        emitter: EventEmitter | None = None,
    ) -> ReflectionVerdict:
        """Ask the LLM to accept, replan, or ask the user to clarify.

        Parsing is fail-safe: a malformed reflection yields an all-false verdict
        so a bad response can never trigger a loop or a spurious clarification.
        """
        system, user = build_reflection_prompt(
            role=self._role,
            query=query,
            results_summary=results_summary,
            criteria_summary=criteria_summary,
        )
        raw_text = await self._chat_fn(system, user)
        verdict = parse_reflection_response(raw_text)
        logger.info(
            "llm_planner.reflection",
            extra={
                "needs_replan": verdict.needs_replan,
                "needs_clarification": verdict.needs_clarification,
                "reason": verdict.reason[:200],
            },
        )
        return verdict
