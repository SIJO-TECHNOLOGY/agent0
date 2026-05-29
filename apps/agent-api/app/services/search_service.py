"""Search service: orchestrates the LangGraph workflow and shapes the API response."""

from __future__ import annotations

import logging
import uuid

from app.graph.nodes import DEFAULT_LLM_PLAN_STEPS, NodeContext
from app.graph.workflow import run_workflow
from app.mcp.client import McpClient
from app.models.api import (
    CandidateCard,
    CandidateCardsUI,
    SearchRequest,
    SearchResponse,
)
from app.models.graph_state import GraphState
from app.services.candidate_mapper import candidate_cards_from_results
from app.services.event_emitter import EventEmitter, NoopEventEmitter
from app.services.llm_planner import LlmPlanner

logger = logging.getLogger(__name__)


class SearchService:
    """Application service that runs the agent workflow for a search."""

    def __init__(
        self,
        mcp_client: McpClient,
        *,
        max_replan_attempts: int = 1,
        mcp_max_retries: int = 2,
        llm_planner: LlmPlanner | None = None,
        max_plan_steps: int = DEFAULT_LLM_PLAN_STEPS,
    ) -> None:
        self._mcp_client = mcp_client
        self._max_replan_attempts = max_replan_attempts
        self._mcp_max_retries = mcp_max_retries
        self._llm_planner = llm_planner
        self._max_plan_steps = max_plan_steps

    @property
    def llm_planner(self) -> LlmPlanner | None:
        return self._llm_planner

    def _build_ctx(
        self, emitter: EventEmitter, *, debug_mode: bool = False
    ) -> NodeContext:
        return NodeContext(
            mcp_client=self._mcp_client,
            max_replan_attempts=self._max_replan_attempts,
            mcp_max_retries=self._mcp_max_retries,
            llm_planner=self._llm_planner,
            max_plan_steps=self._max_plan_steps,
            event_emitter=emitter,
            debug_mode=debug_mode,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Non-streaming search. Events are discarded by NoopEventEmitter."""
        return await self.search_with_events(request, NoopEventEmitter())

    async def search_with_events(
        self,
        request: SearchRequest,
        emitter: EventEmitter,
        *,
        debug_mode: bool = False,
    ) -> SearchResponse:
        """Run the workflow while emitting progress events to ``emitter``.

        Always emits ``search_started`` at the start and ``final_response``
        at the end of a successful run. Failures are raised to the caller
        (the streaming route turns them into ``search_failed`` events).
        """
        conversation_id = f"conv_{uuid.uuid4().hex}"
        planner_mode = "llm" if self._llm_planner is not None else "deterministic"
        logger.info(
            "search.start",
            extra={
                "conversation_id": conversation_id,
                "query": request.query,
                "planner_mode": planner_mode,
            },
        )

        await emitter.emit(
            "search_started",
            {
                "conversation_id": conversation_id,
                "query": request.query,
                "planner_mode": planner_mode,
            },
        )

        ctx = self._build_ctx(emitter, debug_mode=debug_mode)
        initial_state = GraphState(
            original_query=request.query,
            filters=dict(request.filters),
        )
        final_state = await run_workflow(initial_state, ctx)

        candidates = candidate_cards_from_results(final_state.results)

        logger.info(
            "search.complete",
            extra={
                "conversation_id": conversation_id,
                "candidate_count": len(candidates),
                "warning_count": len(final_state.warnings),
                "replan_count": final_state.replan_count,
            },
        )

        response = SearchResponse(
            conversation_id=conversation_id,
            message=_build_message(candidates, final_state),
            ui=CandidateCardsUI(candidates=candidates),
        )
        await emitter.emit("final_response", response.model_dump())
        return response


# Warning codes that indicate the search ran with reduced criteria
# (rather than a hard failure). Surfaced in the message so users know
# the result set is narrower than their request.
_LIMITED_SEARCH_WARNING_CODES: frozenset[str] = frozenset(
    {"experience_filter_unmapped"}
)


def _build_message(
    candidates: list[CandidateCard], final_state: GraphState
) -> str:
    """Compose a short, user-facing reply grounded in the candidate list.

    The message must never hide an internal planner failure: if no tool
    was actually called, say so. If a tool ran but matched nothing, say
    that. If criteria had to be dropped to run the search, append a
    short hint.
    """
    base = _base_message(candidates, final_state)
    hint = _limited_search_hint(final_state)
    if hint:
        return f"{base} {hint}"
    return base


# Tools whose execution counts as "we actually ran a candidate search"
# for the purpose of phrasing the user-facing message. Other tool calls
# (e.g. ``getDictionary`` for filter resolution) are context, not a
# search outcome.
_CANDIDATE_SEARCH_TOOL_NAMES: frozenset[str] = frozenset(
    {"searchCandidates", "search_consultants", "getCandidateDetail"}
)


def _base_message(
    candidates: list[CandidateCard], final_state: GraphState
) -> str:
    count = len(candidates)
    if count == 0:
        if _has_warning(final_state, "clarification_needed"):
            return (
                "Please refine your search with at least one keyword "
                "(skill, technology, role, location, or company)."
            )
        if not final_state.tool_calls:
            return (
                "We couldn't run a candidate search for that query — no "
                "matching MCP tool was available."
            )
        if not _ran_candidate_search(final_state):
            # We executed something (e.g. getDictionary) but never
            # invoked a candidate-producing search tool. Don't claim
            # "no candidates matched" — the search did not complete.
            return (
                "The candidate search did not complete. Please refine "
                "your query and try again."
            )
        if final_state.results:
            # A candidate-producing search returned records but the
            # mapper couldn't normalize them into displayable cards.
            # Surface the truth rather than implying zero matches.
            return (
                "Candidate records were returned, but they could not be "
                "normalized into displayable candidate cards. Check the "
                "stream's results_normalized event for drop reasons."
            )
        return "No candidates matched your search."
    if count == 1:
        name = candidates[0].full_name or candidates[0].id
        return f"Found 1 candidate matching your search: {name}."
    return f"I found {count} candidates matching your search."


def _has_warning(final_state: GraphState, code: str) -> bool:
    return any(w.code == code for w in final_state.warnings)


def _ran_candidate_search(final_state: GraphState) -> bool:
    return any(
        call.tool in _CANDIDATE_SEARCH_TOOL_NAMES
        for call in final_state.tool_calls
    )


def _limited_search_hint(final_state: GraphState) -> str | None:
    triggered = [
        w for w in final_state.warnings if w.code in _LIMITED_SEARCH_WARNING_CODES
    ]
    if not triggered:
        return None
    if any(w.code == "experience_filter_unmapped" for w in triggered):
        return "(experience filter could not be applied)"
    return "(some filters could not be applied)"
