"""Localized user-facing search messages."""

from __future__ import annotations

from app.models.api import CandidateCard
from app.models.graph_state import GraphState
from app.models.tools import ToolCall, ToolCallStatus
from app.models.warnings import Warning
from app.services.search_service import _base_message, _build_message


def _searched_state(*warnings: Warning) -> GraphState:
    return GraphState(
        original_query="java cib",
        tool_calls=[ToolCall(tool="searchCandidates", status=ToolCallStatus.SUCCESS)],
        warnings=list(warnings),
    )


def test_broad_results_message_uses_french_when_requested() -> None:
    message = _build_message(
        [CandidateCard(id=str(i)) for i in range(25)],
        _searched_state(
            Warning(
                code="criteria_visible",
                message=(
                    "visible on candidate profiles but not confirmed in "
                    "technical documents: CIB"
                ),
            )
        ),
        language="fr",
    )

    assert "J’ai trouvé 25 résultats candidats larges" in message
    assert "critères stricts" in message
    assert "visible sur les profils candidats" in message
    assert "I found" not in message
    assert "visible on candidate profiles" not in message


def test_matching_results_message_defaults_to_english() -> None:
    message = _base_message(
        [CandidateCard(id="1"), CandidateCard(id="2")],
        _searched_state(),
    )

    assert message == "I found 2 candidates matching your search."


def test_no_results_message_uses_french_when_requested() -> None:
    message = _base_message([], _searched_state(), language="fr-FR")

    assert message == "Aucun candidat ne correspond à ta recherche."
