"""The clarification UI response built when Agent0 decides to ask the user."""

from __future__ import annotations

from app.models.api import ClarificationUI, SearchResponse
from app.models.graph_state import GraphState
from app.services.search_service import _clarification_response


def _state(question: str, fields: list[str]) -> GraphState:
    return GraphState(
        original_query="dev",
        clarification_question=question,
        clarification_fields=fields,
    )


def test_clarification_response_shape() -> None:
    state = _state("Quelle technologie précisément ?", ["skill", "location"])
    resp = _clarification_response("conv_1", state, language="fr")

    assert isinstance(resp, SearchResponse)
    assert isinstance(resp.ui, ClarificationUI)
    assert resp.ui.type == "clarification"
    assert resp.message == "Quelle technologie précisément ?"
    # First field is required; labels are humanised.
    assert [q.field for q in resp.ui.questions] == ["skill", "location"]
    assert resp.ui.questions[0].required is True
    assert resp.ui.questions[1].required is False
    assert resp.ui.questions[0].label  # non-empty


def test_clarification_response_defaults_field() -> None:
    resp = _clarification_response("c", _state("Précise ta demande", []))
    assert [q.field for q in resp.ui.questions] == ["details"]


def test_clarification_response_serialises_for_frontend() -> None:
    resp = _clarification_response("c", _state("q?", ["skill"]))
    dumped = resp.model_dump()
    assert dumped["ui"]["type"] == "clarification"
    assert dumped["ui"]["questions"][0]["field"] == "skill"
