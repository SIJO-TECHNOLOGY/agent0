"""POST /api/search endpoint tests against the frontend-oriented contract."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

REQUIRED_TOP_KEYS = {"conversation_id", "message", "ui"}
REQUIRED_UI_KEYS = {"type", "candidates"}
REQUIRED_CANDIDATE_KEYS = {
    "id",
    "full_name",
    "title",
    "experience_years",
    "experience_open_ended",
    "location",
    "availability",
    "skills",
    "match_score",
    "is_full_match",
    "unmet_criteria",
    "summary",
    "boond_url",
}


@pytest.mark.asyncio
async def test_search_returns_new_response_contract(client: AsyncClient) -> None:
    response = await client.post(
        "/api/search",
        json={"query": "Find senior Java consultants available next month"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == REQUIRED_TOP_KEYS

    assert isinstance(body["conversation_id"], str) and body["conversation_id"]
    assert body["conversation_id"].startswith("conv_")
    assert isinstance(body["message"], str) and body["message"]

    ui = body["ui"]
    assert set(ui.keys()) == REQUIRED_UI_KEYS
    assert ui["type"] == "candidate_cards"
    assert isinstance(ui["candidates"], list)

    for card in ui["candidates"]:
        assert set(card.keys()) == REQUIRED_CANDIDATE_KEYS
        assert isinstance(card["id"], str) and card["id"]
        assert isinstance(card["skills"], list)


@pytest.mark.asyncio
async def test_search_does_not_leak_internal_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/api/search",
        json={"query": "Find senior Java consultants available next month"},
    )

    assert response.status_code == 200
    body = response.json()
    # The frontend contract must NOT expose internal orchestration state.
    forbidden = {
        "original_query",
        "interpreted_intent",
        "execution_plan",
        "tool_calls",
        "results",
        "confidence",
        "warnings",
        "summary",
    }
    assert not (forbidden & set(body.keys()))


@pytest.mark.asyncio
async def test_search_rejects_blank_query(client: AsyncClient) -> None:
    response = await client.post("/api/search", json={"query": "   "})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_search_rejects_missing_query(client: AsyncClient) -> None:
    response = await client.post("/api/search", json={})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_search_accepts_missing_filters(client: AsyncClient) -> None:
    response = await client.post("/api/search", json={"query": "consultants python"})

    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"


@pytest.mark.asyncio
async def test_search_emits_structured_workflow_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Each workflow node must emit a structured log line at INFO."""
    caplog.set_level("INFO")
    response = await client.post(
        "/api/search", json={"query": "Find senior Python consultants"}
    )
    assert response.status_code == 200

    log_events = {record.message for record in caplog.records}
    # Spot-check the most useful planner/selector/executor markers.
    expected = {
        "graph.analyze_intent",
        "graph.build_plan",
        "graph.select_tools",
        "graph.execute_mcp_tools",
        "graph.generate_final_response",
    }
    assert expected.issubset(log_events)
