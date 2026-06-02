"""Frontend-compatible chat endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_returns_frontend_shape(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat",
        json={"message": "Find senior Java consultants"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"].startswith("conv_")
    assert body["message"]
    assert body["ui"]["type"] == "candidate_cards"
    assert isinstance(body["candidates"], list)
    assert body["candidates"]
    assert body["candidates"][0]["match_score"] >= 0.0


@pytest.mark.asyncio
async def test_chat_rejects_missing_message_and_interaction(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/chat", json={})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_debug_returns_planner_events(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat?debug=true",
        json={"message": "Find senior Java consultants"},
    )

    assert response.status_code == 200
    debug = response.json()["debug"]
    assert debug["planner_mode"] in {"llm", "deterministic"}
    assert isinstance(debug["events"], list)
    assert any(event["type"] == "search_started" for event in debug["events"])


@pytest.mark.asyncio
async def test_conversation_shell_endpoints(client: AsyncClient) -> None:
    create = await client.post(
        "/api/conversations",
        json={"title": "Nouvelle conversation"},
    )
    assert create.status_code == 201
    created = create.json()

    detail = await client.get(f"/api/conversations/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]

    listing = await client.get("/api/conversations")
    assert listing.status_code == 200
    assert any(item["id"] == created["id"] for item in listing.json())

    delete = await client.delete(f"/api/conversations/{created['id']}")
    assert delete.status_code == 204
