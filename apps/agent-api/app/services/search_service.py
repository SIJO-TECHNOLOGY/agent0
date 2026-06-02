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
from app.models.tools import ToolCallStatus
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
        boond_base_url: str = "https://ui.boondmanager.com",
    ) -> None:
        self._mcp_client = mcp_client
        self._max_replan_attempts = max_replan_attempts
        self._mcp_max_retries = mcp_max_retries
        self._llm_planner = llm_planner
        self._max_plan_steps = max_plan_steps
        self._boond_base_url = boond_base_url

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
            boond_base_url=self._boond_base_url,
        )

    async def search(
        self,
        request: SearchRequest,
        *,
        conversation_id: str | None = None,
    ) -> SearchResponse:
        """Non-streaming search. Events are discarded by NoopEventEmitter."""
        return await self.search_with_events(
            request, NoopEventEmitter(), conversation_id=conversation_id
        )

    async def search_with_events(
        self,
        request: SearchRequest,
        emitter: EventEmitter,
        *,
        debug_mode: bool = False,
        conversation_id: str | None = None,
    ) -> SearchResponse:
        """Run the workflow while emitting progress events to ``emitter``.

        Always emits ``search_started`` at the start and ``final_response``
        at the end of a successful run. Failures are raised to the caller
        (the streaming route turns them into ``search_failed`` events).
        """
        conversation_id = conversation_id or f"conv_{uuid.uuid4().hex}"
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

        candidates = candidate_cards_from_results(
            final_state.results, boond_base_url=self._boond_base_url
        )

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
            ui=CandidateCardsUI(
                candidates=candidates,
                title=_build_ui_title(candidates),
                subtitle=_build_ui_subtitle(candidates),
                filters_summary=_build_filters_summary(final_state),
            ),
        )
        await emitter.emit("final_response", response.model_dump())
        return response


# Warning codes that indicate the search ran with reduced criteria
# (rather than a hard failure). Surfaced in the message so users know
# the result set is narrower than their request.
_LIMITED_SEARCH_WARNING_CODES: frozenset[str] = frozenset(
    {
        "experience_filter_unmapped",
        "filter_unresolved",
    }
)


def _build_ui_title(candidates: list[CandidateCard]) -> str | None:
    count = len(candidates)
    if count == 0:
        return None
    plural = "s" if count > 1 else ""
    return f"{count} profil{plural} candidat{plural} trouvé{plural}"


def _build_ui_subtitle(candidates: list[CandidateCard]) -> str | None:
    available = sum(
        1
        for c in candidates
        if c.availability
        and "disponible" in c.availability.lower()
        and "préavis" not in c.availability.lower()
        and "preavis" not in c.availability.lower()
    )
    if available == 0:
        return None
    plural = "s" if available > 1 else ""
    return f"{available} profil{plural} disponible{plural} rapidement"


def _build_filters_summary(final_state: GraphState) -> list[str]:
    """Surface the interpreted search criteria as human-readable filter tags."""
    if final_state.interpreted_intent is None:
        return []
    intent = final_state.interpreted_intent
    tags: list[str] = []
    for entity in intent.entities:
        if isinstance(entity, str) and entity.strip():
            tags.append(entity.strip())
    if "seniority" in intent.constraints:
        tags.append(intent.constraints["seniority"])
    if "min_experience_years" in intent.constraints:
        tags.append(f"{intent.constraints['min_experience_years']}+ ans d'expérience")
    return tags[:6]


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
                "Veuillez affiner votre recherche avec au moins un critère "
                "(compétence, technologie, rôle, localisation ou entreprise)."
            )
        if not final_state.tool_calls:
            return (
                "La recherche n'a pas pu être lancée : aucun outil disponible "
                "ne correspond à cette requête."
            )
        if not _ran_candidate_search(final_state):
            return (
                "La recherche de candidats n'a pas abouti. Veuillez affiner "
                "votre requête et réessayer."
            )
        if _candidate_search_failed(final_state):
            return (
                "La recherche n'a pas pu aboutir en raison d'une erreur technique. "
                "Veuillez réessayer ou reformuler votre requête."
            )
        if final_state.results:
            return (
                "Des enregistrements ont été trouvés, mais n'ont pas pu être "
                "normalisés en fiches candidats."
            )
        if _has_warning(final_state, "no_results_after_fallback"):
            return (
                "Aucun candidat trouvé, même après une recherche élargie. "
                "Essayez d'autres termes ou simplifiez votre requête."
            )
        return "Aucun candidat ne correspond à votre recherche."
    unverified = (
        _has_warning(final_state, "criteria_unverified")
        or _has_warning(final_state, "criteria_visible")
        or _has_warning(final_state, "search_broadened")
    )
    if count == 1:
        name = candidates[0].full_name or candidates[0].id
        if unverified:
            return (
                f"J'ai trouvé un profil proche de votre recherche : {name}. "
                "Certains points restent à confirmer dans le dossier candidat."
            )
        return f"J'ai trouvé un profil qui correspond à votre recherche : {name}."
    if unverified:
        return (
            f"J'ai trouvé {count} profils proches de votre recherche. "
            "Je les ai classés selon les informations disponibles ; certains points "
            "restent à confirmer dans les dossiers candidats."
        )
    return f"J'ai trouvé {count} profils correspondant à votre recherche."


def _has_warning(final_state: GraphState, code: str) -> bool:
    return any(w.code == code for w in final_state.warnings)


def _ran_candidate_search(final_state: GraphState) -> bool:
    return any(
        call.tool in _CANDIDATE_SEARCH_TOOL_NAMES
        for call in final_state.tool_calls
    )


def _candidate_search_failed(final_state: GraphState) -> bool:
    return any(
        call.tool in _CANDIDATE_SEARCH_TOOL_NAMES
        and call.status is ToolCallStatus.FAILED
        for call in final_state.tool_calls
    )


def _limited_search_hint(final_state: GraphState) -> str | None:
    triggered = [
        w for w in final_state.warnings if w.code in _LIMITED_SEARCH_WARNING_CODES
    ]
    if not triggered:
        return None
    clauses: list[str] = []
    if any(w.code == "search_broadened" for w in triggered):
        clauses.append("recherche élargie pour trouver des candidats")
    if any(w.code == "experience_filter_unmapped" for w in triggered):
        clauses.append("filtre d'expérience non appliqué")
    if any(w.code == "filter_unresolved" for w in triggered):
        clauses.append("certains filtres n'ont pas pu être appliqués")
    unverified = next(
        (w for w in triggered if w.code == "criteria_unverified"), None
    )
    if unverified is not None and unverified.message:
        clauses.append(unverified.message)
    visible = next(
        (w for w in triggered if w.code == "criteria_visible"), None
    )
    if visible is not None and visible.message:
        clauses.append(visible.message)
    if not clauses:
        clauses.append("some filters could not be applied")
    return "(" + "; ".join(clauses) + ")"
