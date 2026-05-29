"""Pydantic schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.api import (
    CandidateCard,
    CandidateCardsUI,
    SearchRequest,
    SearchResponse,
)
from app.models.tools import ToolCall, ToolCallStatus


def test_search_request_strips_query() -> None:
    request = SearchRequest(query="  python consultants  ")
    assert request.query == "python consultants"
    assert request.filters == {}


def test_search_request_rejects_blank_query() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


def test_search_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="hi", unexpected="value")  # type: ignore[call-arg]


def test_tool_call_defaults() -> None:
    call = ToolCall(tool="search_consultants", status=ToolCallStatus.EMPTY)
    assert call.attempts == 1
    assert call.latency_ms == 0
    assert call.result_count == 0
    assert call.error_message is None


def test_candidate_card_unknown_scalars_default_to_none() -> None:
    card = CandidateCard(id="c-1")
    assert card.full_name is None
    assert card.title is None
    assert card.experience_years is None
    assert card.location is None
    assert card.availability is None
    assert card.match_score is None
    assert card.summary is None
    assert card.boond_url is None


def test_candidate_card_skills_default_to_empty_list() -> None:
    card = CandidateCard(id="c-1")
    assert card.skills == []


def test_candidate_card_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CandidateCard(id="c-1", debug_payload="x")  # type: ignore[call-arg]


def test_candidate_cards_ui_defaults_to_empty_candidates() -> None:
    ui = CandidateCardsUI()
    assert ui.type == "candidate_cards"
    assert ui.candidates == []


def test_candidate_cards_ui_rejects_other_types() -> None:
    with pytest.raises(ValidationError):
        CandidateCardsUI(type="other")  # type: ignore[arg-type]


def test_search_response_round_trip_with_full_candidate() -> None:
    response = SearchResponse(
        conversation_id="conv_abc",
        message="Found 1 candidate matching your search.",
        ui=CandidateCardsUI(
            candidates=[
                CandidateCard(
                    id="41924",
                    full_name="Sarah Martin",
                    title="Backend Java Engineer",
                    experience_years=7.0,
                    location="Paris, France",
                    availability="Available immediately",
                    skills=["Java", "Spring", "Kafka"],
                    match_score=None,
                    summary="Confirmed backend profile.",
                    boond_url=None,
                )
            ]
        ),
    )

    body = response.model_dump()
    assert body["conversation_id"] == "conv_abc"
    assert body["ui"]["type"] == "candidate_cards"
    assert body["ui"]["candidates"][0]["full_name"] == "Sarah Martin"
    assert body["ui"]["candidates"][0]["match_score"] is None


def test_search_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SearchResponse(
            conversation_id="conv_abc",
            message="x",
            ui=CandidateCardsUI(),
            debug_state={},  # type: ignore[call-arg]
        )
