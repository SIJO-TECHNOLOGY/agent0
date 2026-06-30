"""Frontend-compatible chat endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.chat import _combine_query


def test_combine_query_starts_fresh() -> None:
    assert _combine_query("", "dev C# chez cacib") == "dev C# chez cacib"


def test_combine_query_accumulates_followup() -> None:
    assert (
        _combine_query("dev C# chez cacib", "10 ans d'expérience")
        == "dev C# chez cacib 10 ans d'expérience"
    )


def test_combine_query_ignores_bare_affirmation() -> None:
    # "oui" confirms a clarification but adds no new criteria.
    assert _combine_query("dev C# chez cacib", "oui") == "dev C# chez cacib"


def test_combine_query_skips_duplicate() -> None:
    assert _combine_query("dev C# chez cacib", "dev C#") == "dev C# chez cacib"


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
async def test_followup_accumulates_conversation_context(client: AsyncClient) -> None:
    # First turn establishes context.
    first = await client.post(
        "/api/chat?debug=true", json={"message": "dev C# chez cacib"}
    )
    assert first.status_code == 200
    conv_id = first.json()["conversation_id"]
    assert first.json()["debug"]["effective_query"] == "dev C# chez cacib"

    # A follow-up in the SAME conversation refines, not resets: the prior
    # criteria (cacib) are retained.
    second = await client.post(
        "/api/chat?debug=true",
        json={"message": "10 ans d'expérience", "conversation_id": conv_id},
    )
    assert second.status_code == 200
    effective = second.json()["debug"]["effective_query"]
    assert "cacib" in effective
    assert "10 ans" in effective


@pytest.mark.asyncio
async def test_conversation_records_messages(client: AsyncClient) -> None:
    resp = await client.post("/api/chat", json={"message": "Find Java consultants"})
    conv_id = resp.json()["conversation_id"]
    detail = await client.get(f"/api/conversations/{conv_id}")
    messages = detail.json()["messages"]
    assert any(m["role"] == "user" for m in messages)
    assert any(m["role"] == "assistant" for m in messages)


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
