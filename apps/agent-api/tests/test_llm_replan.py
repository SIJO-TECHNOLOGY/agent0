"""Tests for the bounded, LLM-driven replan (reflection) loop."""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    NodeContext,
    plan_with_llm,
    reflect_on_results,
    should_replan_llm,
)
from app.graph.workflow import run_workflow
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, LlmToolPlan, PlannedToolCall
from app.models.results import SearchResult
from app.models.tools import McpTool
from app.services.llm_planner import ReflectionVerdict


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))


class _ReflectPlanner:
    """Planner stub exposing only reflect() with a fixed verdict."""

    def __init__(self, verdict: ReflectionVerdict) -> None:
        self._verdict = verdict
        self.calls = 0

    async def reflect(self, *, query, results_summary, criteria_summary="", emitter=None):
        self.calls += 1
        return self._verdict


def _ctx(planner, *, emitter=None, max_replan=1, use_llm_replan=True, skip=0.8,
         allow_clarification=True):
    return NodeContext(
        mcp_client=MockMcpClient(),
        max_replan_attempts=max_replan,
        llm_planner=planner,
        use_llm_replan=use_llm_replan,
        replan_skip_score=skip,
        event_emitter=emitter or _RecordingEmitter(),
        allow_clarification=allow_clarification,
    )


def _result(cid: str, *, score: float, full: bool, unmet=()) -> SearchResult:
    return SearchResult(
        id=cid,
        type="candidate",
        title="Java Dev",
        score=score,
        source_tool="searchCandidates",
        data={"firstName": f"C{cid}"},
        is_full_match=full,
        unmet_criteria=list(unmet),
    )


def _weak_state() -> GraphState:
    return GraphState(
        original_query="java dev 10 years in CIB",
        interpreted_intent=InterpretedIntent(objective="find", entities=["java"]),
        results=[_result("1", score=0.5, full=False, unmet=["CIB", "10+ years"])],
    )


# ---------------------------------------------------------------------------
# reflect_on_results — the LLM-driven replan decision + its safety gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_requests_clarification() -> None:
    planner = _ReflectPlanner(
        ReflectionVerdict(
            needs_clarification=True,
            clarification_question="Quelle technologie précisément ?",
            clarification_fields=["skill"],
        )
    )
    out = await reflect_on_results(_weak_state(), _ctx(planner))
    assert out.clarification_question == "Quelle technologie précisément ?"
    assert out.clarification_fields == ["skill"]
    assert out.replan_feedback == ""  # clarify, not replan


@pytest.mark.asyncio
async def test_clarification_takes_precedence_over_replan() -> None:
    planner = _ReflectPlanner(
        ReflectionVerdict(
            needs_replan=True,
            guidance="broaden",
            needs_clarification=True,
            clarification_question="Quelle localisation ?",
            clarification_fields=["location"],
        )
    )
    out = await reflect_on_results(_weak_state(), _ctx(planner))
    assert out.clarification_question == "Quelle localisation ?"
    assert out.replan_feedback == ""
    assert out.replan_count == 0


@pytest.mark.asyncio
async def test_clarification_ignored_when_disabled() -> None:
    planner = _ReflectPlanner(
        ReflectionVerdict(
            needs_clarification=True,
            clarification_question="?",
            clarification_fields=["skill"],
            needs_replan=True,
            guidance="broaden",
        )
    )
    out = await reflect_on_results(_weak_state(), _ctx(planner, allow_clarification=False))
    # Clarification off → falls through to the replan path.
    assert out.clarification_question == ""
    assert out.replan_feedback == "broaden"


@pytest.mark.asyncio
async def test_reflect_requests_replan_when_llm_says_so() -> None:
    emitter = _RecordingEmitter()
    planner = _ReflectPlanner(
        ReflectionVerdict(needs_replan=True, reason="weak", guidance="broaden CIB")
    )
    result = await reflect_on_results(_weak_state(), _ctx(planner, emitter=emitter))

    assert planner.calls == 1
    assert result.replan_count == 1
    assert result.replan_feedback == "broaden CIB"
    assert any(code == "replan_requested" for code, _ in emitter.events)


@pytest.mark.asyncio
async def test_reflect_no_replan_when_llm_declines() -> None:
    planner = _ReflectPlanner(ReflectionVerdict(needs_replan=False, guidance=""))
    result = await reflect_on_results(_weak_state(), _ctx(planner))
    assert planner.calls == 1
    assert result.replan_count == 0
    assert result.replan_feedback == ""


@pytest.mark.asyncio
async def test_reflect_skipped_when_budget_exhausted() -> None:
    planner = _ReflectPlanner(ReflectionVerdict(needs_replan=True, guidance="x"))
    state = _weak_state().model_copy(update={"replan_count": 1})
    result = await reflect_on_results(state, _ctx(planner, max_replan=1))
    assert planner.calls == 0  # gate prevents the LLM call entirely
    assert result.replan_feedback == ""


@pytest.mark.asyncio
async def test_reflect_skipped_when_results_already_strong() -> None:
    planner = _ReflectPlanner(ReflectionVerdict(needs_replan=True, guidance="x"))
    state = GraphState(
        original_query="q",
        results=[_result("1", score=0.95, full=True)],  # full match -> good enough
    )
    result = await reflect_on_results(state, _ctx(planner))
    assert planner.calls == 0
    assert result.replan_feedback == ""


@pytest.mark.asyncio
async def test_reflect_disabled_by_flag() -> None:
    planner = _ReflectPlanner(ReflectionVerdict(needs_replan=True, guidance="x"))
    result = await reflect_on_results(
        _weak_state(), _ctx(planner, use_llm_replan=False)
    )
    assert planner.calls == 0
    assert result.replan_feedback == ""


@pytest.mark.asyncio
async def test_reflect_noop_when_planner_has_no_reflect() -> None:
    result = await reflect_on_results(_weak_state(), _ctx(object()))
    assert result.replan_feedback == ""


@pytest.mark.asyncio
async def test_reflect_fail_safe_on_error() -> None:
    class _Boom:
        async def reflect(self, **_kwargs):
            raise RuntimeError("llm down")

    result = await reflect_on_results(_weak_state(), _ctx(_Boom()))
    assert result.replan_count == 0
    assert result.replan_feedback == ""


# ---------------------------------------------------------------------------
# routing + feedback consumption
# ---------------------------------------------------------------------------


def test_should_replan_llm_routes_on_feedback() -> None:
    pending = GraphState(original_query="q", replan_feedback="broaden")
    done = GraphState(original_query="q", replan_feedback="")
    assert should_replan_llm(pending) == "plan_with_llm"
    assert should_replan_llm(done) == "generate_final_response"


@pytest.mark.asyncio
async def test_plan_with_llm_consumes_and_forwards_feedback() -> None:
    captured: dict[str, str] = {}

    class _CapturePlanner:
        async def plan(self, *, query, filters, tools, constraints, emitter=None, feedback=""):
            captured["feedback"] = feedback
            return LlmToolPlan(interpreted_intent={"objective": "x"}, plan=[])

    state = GraphState(original_query="q", replan_feedback="broaden to CIB")
    result = await plan_with_llm(state, _ctx(_CapturePlanner()))

    assert captured["feedback"] == "broaden to CIB"
    assert result.replan_feedback == ""  # consumed exactly once


class _NoBoundsPlanner:
    """Planner stub that never emits experience bounds in its constraints."""

    async def plan(self, *, query, filters, tools, constraints, emitter=None, feedback=""):
        return LlmToolPlan(
            interpreted_intent={
                "objective": "find",
                "entities": ["java"],
                "constraints": {},
            },
            plan=[],
        )


@pytest.mark.asyncio
async def test_plan_with_llm_backfills_experience_bounds_from_query() -> None:
    # The LLM omitted the seniority constraint the user clearly stated; the
    # deterministic backstop must restore it so ranking scores the dimension.
    state = GraphState(original_query="dev java 5 ans d'expérience")
    result = await plan_with_llm(state, _ctx(_NoBoundsPlanner()))

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.constraints["min_experience_years"] == "5"


@pytest.mark.asyncio
async def test_plan_with_llm_skips_backfill_on_feedback_replan() -> None:
    # On a reflection-triggered replan the LLM may have deliberately dropped
    # the bound (e.g. "broaden the search") — do not re-add it.
    state = GraphState(
        original_query="dev java 5 ans d'expérience",
        replan_feedback="drop the seniority constraint and broaden",
    )
    result = await plan_with_llm(state, _ctx(_NoBoundsPlanner()))

    assert result.interpreted_intent is not None
    assert "min_experience_years" not in result.interpreted_intent.constraints


@pytest.mark.asyncio
async def test_plan_with_llm_keeps_llm_emitted_bounds() -> None:
    # When the LLM already interpreted the bounds, the backstop must not touch them.
    class _BoundsPlanner:
        async def plan(self, *, query, filters, tools, constraints, emitter=None, feedback=""):
            return LlmToolPlan(
                interpreted_intent={
                    "objective": "find",
                    "entities": ["java"],
                    "constraints": {"min_experience_years": "7"},
                },
                plan=[],
            )

    state = GraphState(original_query="dev java 5 ans d'expérience")
    result = await plan_with_llm(state, _ctx(_BoundsPlanner()))

    assert result.interpreted_intent is not None
    assert result.interpreted_intent.constraints["min_experience_years"] == "7"


# ---------------------------------------------------------------------------
# end-to-end: the bounded loop runs once through the compiled LLM graph
# ---------------------------------------------------------------------------

_SEARCH_TOOL = McpTool(
    name="searchCandidates",
    description="Search candidates.",
    input_schema={"type": "object", "properties": {"keywords": {"type": "string"}}},
)
_DICT_TOOL = McpTool(
    name="getDictionary",
    description="Dictionary.",
    input_schema={"type": "object", "properties": {}},
)


class _LoopPlanner:
    """Plans a java search and, on first reflection, asks for one replan."""

    def __init__(self) -> None:
        self.plan_feedbacks: list[str] = []
        self.reflect_calls = 0

    async def plan(self, *, query, filters, tools, constraints, emitter=None, feedback=""):
        self.plan_feedbacks.append(feedback)
        return LlmToolPlan(
            interpreted_intent={
                "objective": "find",
                "entities": ["java"],
                "constraints": {"min_experience_years": "10"},
            },
            plan=[PlannedToolCall(tool_name="searchCandidates", inputs={"keywords": "java"})],
        )

    async def reflect(self, *, query, results_summary, criteria_summary="", emitter=None):
        self.reflect_calls += 1
        return ReflectionVerdict(needs_replan=True, reason="weak", guidance="add seniority")


@pytest.mark.asyncio
async def test_llm_workflow_runs_one_bounded_replan() -> None:
    async def search_handler(_inputs):
        # Java present but no experience -> seniority unmet -> weak (score < skip).
        return [{"id": 1, "attributes": {"jobTitle": "Java Engineer"}}]

    async def dict_handler(_inputs):
        return [{"setting": {"experience": [], "tool": [{"id": "j", "label": "Java"}]}}]

    planner = _LoopPlanner()
    ctx = NodeContext(
        mcp_client=MockMcpClient(
            tools=[_SEARCH_TOOL, _DICT_TOOL],
            handlers={"searchCandidates": search_handler, "getDictionary": dict_handler},
        ),
        max_replan_attempts=1,
        llm_planner=planner,
    )
    final = await run_workflow(GraphState(original_query="java dev 10 years"), ctx)

    # Exactly one bounded replan: planned twice (2nd with feedback), reflected
    # once (budget then blocks a 2nd reflection), and feedback was consumed.
    assert planner.plan_feedbacks == ["", "add seniority"]
    assert planner.reflect_calls == 1
    assert final.replan_count == 1
    assert final.replan_feedback == ""
    assert final.summary
