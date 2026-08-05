"""Conversation CRUD routes backed by the durable store."""

from __future__ import annotations

import json

from httpx import AsyncClient


async def test_create_list_and_get(client: AsyncClient) -> None:
    created = await client.post("/api/conversations", json={})
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert created.json()["title"] == "Nouvelle conversation"

    listed = await client.get("/api/conversations")
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [conversation_id]

    detail = await client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []


async def test_chat_turn_is_persisted_with_cards(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat", json={"message": "développeur java expérimenté"}
    )
    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]

    listed = await client.get("/api/conversations")
    titles = {c["id"]: c["title"] for c in listed.json()}
    assert titles[conversation_id] == "développeur java expérimenté"

    detail = await client.get(f"/api/conversations/{conversation_id}")
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "développeur java expérimenté"
    assistant = messages[1]
    assert assistant.get("ui", {}).get("type") == "candidate_cards"
    assert assistant["ui"]["candidates"], "cards must be persisted for replay"


async def test_stream_turn_is_persisted(client: AsyncClient) -> None:
    async with client.stream(
        "POST", "/api/search/stream", json={"query": "consultant python"}
    ) as response:
        assert response.status_code == 200
        body = "".join([chunk async for chunk in response.aiter_text()])
    assert "final_response" in body

    listed = await client.get("/api/conversations")
    assert listed.status_code == 200
    conversations = listed.json()
    assert len(conversations) == 1
    assert conversations[0]["title"] == "consultant python"

    detail = await client.get(f"/api/conversations/{conversations[0]['id']}")
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    # The persisted UI payload matches what the stream displayed.
    final_payload = json.loads(
        [line for line in body.splitlines() if line.startswith("data: ")][-1][6:]
    )
    if final_payload.get("ui", {}).get("candidates"):
        assert messages[1]["ui"]["candidates"] == final_payload["ui"]["candidates"]


async def test_rename_conversation(client: AsyncClient) -> None:
    created = await client.post("/api/conversations", json={})
    conversation_id = created.json()["id"]

    renamed = await client.patch(
        f"/api/conversations/{conversation_id}", json={"title": "Mission BNP"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Mission BNP"

    missing = await client.patch(
        "/api/conversations/conv_missing", json={"title": "x"}
    )
    assert missing.status_code == 404

    blank = await client.patch(
        f"/api/conversations/{conversation_id}", json={"title": "   "}
    )
    assert blank.status_code == 400


async def test_delete_conversation_really_deletes(client: AsyncClient) -> None:
    response = await client.post("/api/chat", json={"message": "dev java"})
    conversation_id = response.json()["conversation_id"]

    deleted = await client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await client.get("/api/conversations")).json() == []

    again = await client.delete(f"/api/conversations/{conversation_id}")
    assert again.status_code == 404


async def test_candidate_detail_survives_restart(client: AsyncClient) -> None:
    from app.api import chat as chat_module

    response = await client.post("/api/chat", json={"message": "dev java"})
    detail = await client.get(
        f"/api/conversations/{response.json()['conversation_id']}"
    )
    cards = detail.json()["messages"][1]["ui"]["candidates"]
    candidate_id = str(cards[0]["id"])

    # Simulate a restart: the in-process candidate cache is gone.
    chat_module._CANDIDATES.clear()

    fetched = await client.get(f"/api/candidates/{candidate_id}")
    assert fetched.status_code == 200
    assert str(fetched.json()["id"]) == candidate_id

    missing = await client.get("/api/candidates/unknown-id")
    assert missing.status_code == 404


async def test_delete_all_conversations(client: AsyncClient) -> None:
    await client.post("/api/chat", json={"message": "dev java"})
    await client.post("/api/conversations", json={})
    assert len((await client.get("/api/conversations")).json()) == 2

    cleared = await client.delete("/api/conversations")
    assert cleared.status_code == 204
    assert (await client.get("/api/conversations")).json() == []
