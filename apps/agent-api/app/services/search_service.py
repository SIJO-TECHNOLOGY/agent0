"""Search service: orchestrates the LangGraph workflow and shapes the API response."""

from __future__ import annotations

import logging
import uuid

from app.agents.agent1.reconciler import Agent1Reconciler
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
from app.services.event_emitter import (
    DecisionTraceEmitter,
    EventEmitter,
    NoopEventEmitter,
)
from app.services.llm_planner import LlmPlanner
from app.services.semantic_scorer import SemanticScorer

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
        use_llm_replan: bool = True,
        replan_skip_score: float = 0.8,
        agent_trace: bool = False,
        agent_trace_verbose: bool = False,
        semantic_scorer: SemanticScorer | None = None,
        semantic_boost_weight: float = 0.15,
        agent1_reconciler: Agent1Reconciler | None = None,
    ) -> None:
        self._mcp_client = mcp_client
        self._max_replan_attempts = max_replan_attempts
        self._mcp_max_retries = mcp_max_retries
        self._llm_planner = llm_planner
        self._max_plan_steps = max_plan_steps
        self._use_llm_replan = use_llm_replan
        self._replan_skip_score = replan_skip_score
        self._agent_trace = agent_trace
        self._agent_trace_verbose = agent_trace_verbose
        self._semantic_scorer = semantic_scorer
        self._semantic_boost_weight = semantic_boost_weight
        self._agent1_reconciler = agent1_reconciler

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
            use_llm_replan=self._use_llm_replan,
            replan_skip_score=self._replan_skip_score,
            event_emitter=emitter,
            debug_mode=debug_mode,
            semantic_scorer=self._semantic_scorer,
            semantic_boost_weight=self._semantic_boost_weight,
            agent1_reconciler=self._agent1_reconciler,
        )

    async def search(
        self, request: SearchRequest, *, ui_language: str | None = None
    ) -> SearchResponse:
        """Non-streaming search. Events are discarded by NoopEventEmitter."""
        return await self.search_with_events(
            request, NoopEventEmitter(), ui_language=ui_language
        )

    async def search_with_events(
        self,
        request: SearchRequest,
        emitter: EventEmitter,
        *,
        debug_mode: bool = False,
        ui_language: str | None = None,
    ) -> SearchResponse:
        """Run the workflow while emitting progress events to ``emitter``.

        Always emits ``search_started`` at the start and ``final_response``
        at the end of a successful run. Failures are raised to the caller
        (the streaming route turns them into ``search_failed`` events).
        """
        conversation_id = f"conv_{uuid.uuid4().hex}"
        planner_mode = "llm" if self._llm_planner is not None else "deterministic"
        # Wrap at the outermost point so the readable decision trace also
        # captures the search header and final result, not just node events.
        if self._agent_trace:
            emitter = DecisionTraceEmitter(
                emitter, verbose=self._agent_trace_verbose
            )
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
            message=_build_message(candidates, final_state, language=ui_language),
            ui=CandidateCardsUI(candidates=candidates),
        )
        await emitter.emit("final_response", response.model_dump())
        return response


# Warning codes that indicate the search ran with reduced criteria
# (rather than a hard failure). Surfaced in the message so users know
# the result set is narrower than their request.
_LIMITED_SEARCH_WARNING_CODES: frozenset[str] = frozenset(
    {
        "experience_filter_unmapped",
        "criteria_unverified",
        "criteria_visible",
        "filter_unresolved",
        "search_broadened",
    }
)


def _build_message(
    candidates: list[CandidateCard],
    final_state: GraphState,
    *,
    language: str | None = None,
) -> str:
    """Compose a short, user-facing reply grounded in the candidate list.

    The message must never hide an internal planner failure: if no tool
    was actually called, say so. If a tool ran but matched nothing, say
    that. If criteria had to be dropped to run the search, append a
    short hint.
    """
    lang = _normalize_language(language)
    base = _base_message(candidates, final_state, language=lang)
    hint = _limited_search_hint(final_state, language=lang)
    message = f"{base} {hint}" if hint else base
    # A named-person miss is the most important context — lead with it so the
    # user knows these are fallback results, not the person they asked for.
    name_note = next(
        (
            _localize_warning_message(w.code, w.message, lang)
            for w in final_state.warnings
            if w.code == "name_not_found" and w.message
        ),
        None,
    )
    if name_note:
        return f"{name_note} {message}"
    return message


# Tools whose execution counts as "we actually ran a candidate search"
# for the purpose of phrasing the user-facing message. Other tool calls
# (e.g. ``getDictionary`` for filter resolution) are context, not a
# search outcome.
_CANDIDATE_SEARCH_TOOL_NAMES: frozenset[str] = frozenset(
    {"searchCandidates", "search_consultants", "getCandidateDetail"}
)


def _base_message(
    candidates: list[CandidateCard],
    final_state: GraphState,
    *,
    language: str | None = None,
) -> str:
    lang = _normalize_language(language)
    count = len(candidates)
    if count == 0:
        if _has_warning(final_state, "clarification_needed"):
            return (
                "Précise ta recherche avec au moins un mot-clé "
                "(compétence, technologie, rôle, localisation ou entreprise)."
                if lang == "fr"
                else "Please refine your search with at least one keyword "
                "(skill, technology, role, location, or company)."
            )
        if not final_state.tool_calls:
            return (
                "Impossible de lancer une recherche candidat pour cette demande : "
                "aucun outil MCP correspondant n’était disponible."
                if lang == "fr"
                else "We couldn't run a candidate search for that query — no "
                "matching MCP tool was available."
            )
        if not _ran_candidate_search(final_state):
            return (
                "La recherche candidat ne s’est pas terminée. Précise ta "
                "demande puis réessaie."
                if lang == "fr"
                else "The candidate search did not complete. Please refine "
                "your query and try again."
            )
        if _candidate_search_failed(final_state):
            return (
                "La recherche candidat n’a pas pu aboutir car un outil de "
                "recherche a échoué. Réessaie ou ajuste ta demande."
                if lang == "fr"
                else "The candidate search could not be completed because a "
                "search tool failed. Please try again or adjust your query."
            )
        if final_state.results:
            return (
                "Des fiches candidats ont été retournées, mais elles n’ont "
                "pas pu être normalisées en cartes affichables. Consulte "
                "l’événement results_normalized du flux pour les raisons de rejet."
                if lang == "fr"
                else "Candidate records were returned, but they could not be "
                "normalized into displayable candidate cards. Check the "
                "stream's results_normalized event for drop reasons."
            )
        if _has_warning(final_state, "no_results_after_fallback"):
            return (
                "Aucun candidat ne correspond à ta recherche, même après "
                "des recherches élargies. Essaie avec des termes différents ou moins nombreux."
                if lang == "fr"
                else "No candidates matched your search, even after broader "
                "fallback searches. Try different or fewer terms."
            )
        return (
            "Aucun candidat ne correspond à ta recherche."
            if lang == "fr"
            else "No candidates matched your search."
        )
    unverified = (
        _has_warning(final_state, "criteria_unverified")
        or _has_warning(final_state, "criteria_visible")
        or _has_warning(final_state, "search_broadened")
        or _has_warning(final_state, "name_not_found")
    )
    if count == 1:
        name = candidates[0].full_name or candidates[0].id
        if unverified:
            return (
                f"J’ai trouvé 1 résultat candidat large ({name}), mais les "
                "critères stricts n’ont pas pu être entièrement vérifiés. "
                "J’affiche le profil le plus proche, classé selon les éléments disponibles."
                if lang == "fr"
                else f"I found 1 broad candidate result ({name}), but the strict "
                "criteria could not be fully verified. Showing the closest "
                "match ranked by available evidence."
            )
        return (
            f"J’ai trouvé 1 candidat correspondant à ta recherche : {name}."
            if lang == "fr"
            else f"Found 1 candidate matching your search: {name}."
        )
    if unverified:
        return (
            f"J’ai trouvé {count} résultats candidats larges, mais les "
            "critères stricts n’ont pas pu être entièrement vérifiés. "
            "J’affiche les profils les plus proches, classés selon les éléments disponibles."
            if lang == "fr"
            else f"I found {count} broad candidate results, but the strict "
            "criteria could not be fully verified. Showing the closest "
            "matches ranked by available evidence."
        )
    return (
        f"J’ai trouvé {count} candidats correspondant à ta recherche."
        if lang == "fr"
        else f"I found {count} candidates matching your search."
    )


def _normalize_language(language: str | None) -> str:
    if not language:
        return "en"
    return "fr" if str(language).strip().lower().startswith("fr") else "en"


def _localize_warning_message(code: str, message: str | None, language: str) -> str:
    if language != "fr" or not message:
        return message or ""
    if code == "criteria_unverified" and message.startswith("could not verify: "):
        return "impossible à vérifier : " + message.split(": ", 1)[1]
    if code == "criteria_visible" and message.startswith(
        "visible on candidate profiles but not confirmed in technical documents: "
    ):
        return (
            "visible sur les profils candidats mais non confirmé dans les "
            "documents techniques : " + message.split(": ", 1)[1]
        )
    if code == "search_broadened":
        return (
            "La recherche initiale a été élargie pour trouver des candidats ; "
            "certains critères peuvent ne pas être strictement appliqués."
        )
    if code == "name_not_found" and message.startswith("No candidate matching the name '"):
        try:
            name = message.split("'", 2)[1]
        except IndexError:
            return message
        if "showing candidates matching the other criteria instead" in message:
            return (
                f"Aucun candidat correspondant au nom '{name}' n’a été trouvé ; "
                "j’affiche plutôt les candidats correspondant aux autres critères."
            )
        if "no candidates matched the other criteria either" in message:
            return (
                f"Aucun candidat correspondant au nom '{name}' n’a été trouvé, "
                "et aucun candidat ne correspond non plus aux autres critères."
            )
    return message


def _limited_search_hint(
    final_state: GraphState, *, language: str | None = None
) -> str | None:
    lang = _normalize_language(language)
    triggered = [
        w for w in final_state.warnings if w.code in _LIMITED_SEARCH_WARNING_CODES
    ]
    if not triggered:
        return None
    clauses: list[str] = []
    if any(w.code == "search_broadened" for w in triggered):
        clauses.append(
            "recherche élargie pour trouver des candidats"
            if lang == "fr"
            else "search was broadened to find candidates"
        )
    if any(w.code == "experience_filter_unmapped" for w in triggered):
        clauses.append(
            "filtre d’expérience non applicable"
            if lang == "fr"
            else "experience filter could not be applied"
        )
    if any(w.code == "filter_unresolved" for w in triggered):
        clauses.append(
            "certains filtres prévus n’ont pas pu être appliqués"
            if lang == "fr"
            else "some planned filters could not be applied"
        )
    unverified = next(
        (w for w in triggered if w.code == "criteria_unverified"), None
    )
    if unverified is not None and unverified.message:
        clauses.append(
            _localize_warning_message(unverified.code, unverified.message, lang)
        )
    visible = next(
        (w for w in triggered if w.code == "criteria_visible"), None
    )
    if visible is not None and visible.message:
        clauses.append(_localize_warning_message(visible.code, visible.message, lang))
    if not clauses:
        clauses.append(
            "certains filtres n’ont pas pu être appliqués"
            if lang == "fr"
            else "some filters could not be applied"
        )
    return "(" + "; ".join(clauses) + ")"


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
