"""Frontend-compatible chat endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.chat import (
    _CONVERSATION_RESULTS,
    _PAGE_SIZE,
    _combine_query,
    _is_more_request,
    _serve_page,
)


def test_is_more_request() -> None:
    for phrase in ("d'autres", "plus", "more", "next", "encore", "  D'AUTRES  "):
        assert _is_more_request(phrase) is True
    for phrase in ("dev java", "tech lead amundi", "python senior"):
        assert _is_more_request(phrase) is False


def test_serve_page_paginates_pool() -> None:
    pool = [{"id": f"c{i}"} for i in range(_PAGE_SIZE + 3)]  # one full page + 3
    _CONVERSATION_RESULTS["conv_pg"] = {"candidates": pool, "shown": 0, "total": len(pool)}
    try:
        first = _serve_page("conv_pg")
        assert len(first.candidates) == _PAGE_SIZE
        assert "1-" in first.message

        second = _serve_page("conv_pg")
        assert len(second.candidates) == 3  # the remainder
        # The two pages are disjoint (new candidates).
        ids1 = {c["id"] for c in first.candidates}
        ids2 = {c["id"] for c in second.candidates}
        assert ids1.isdisjoint(ids2)

        third = _serve_page("conv_pg")
        assert third.candidates == []
        assert "Plus de candidats" in third.message
    finally:
        _CONVERSATION_RESULTS.pop("conv_pg", None)


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
async def test_more_request_is_pagination_not_new_search(client: AsyncClient) -> None:
    first = await client.post("/api/chat", json={"message": "java spring kafka dev"})
    conv_id = first.json()["conversation_id"]
    assert first.json()["ui"]["type"] == "candidate_cards"

    # "d'autres" is handled as pagination → still a candidate_cards UI (never a
    # clarification), serving the next page (or a "no more" message).
    more = await client.post(
        "/api/chat", json={"message": "d'autres", "conversation_id": conv_id}
    )
    assert more.status_code == 200
    body = more.json()
    assert body["ui"]["type"] == "candidate_cards"
    assert "candidats" in body["message"].lower()


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


@pytest.mark.asyncio
async def test_chat_response_includes_session_contract(client: AsyncClient) -> None:
    response = await client.post("/api/chat", json={"message": "Find Java consultants"})

    assert response.status_code == 200
    body = response.json()
    assert body["sessionId"] == body["conversation_id"]
    assert body["answer"] == body["message"]
    assert body["context"]["candidateCount"] >= 0
    assert "currentSearch" in body["context"]
    assert "lastFilters" in body["context"]


@pytest.mark.asyncio
async def test_same_session_recovers_context(client: AsyncClient) -> None:
    first = await client.post("/api/chat", json={"message": "Cherche des developpeurs Java senior"})
    session_id = first.json()["sessionId"]

    second = await client.post(
        "/api/chat?debug=true",
        json={"message": "Ajoute Spring Boot", "sessionId": session_id},
    )

    assert second.status_code == 200
    body = second.json()
    assert body["sessionId"] == session_id
    assert body["debug"]["isFollowUp"] is True
    assert body["debug"]["conversationHistorySize"] >= 2


@pytest.mark.asyncio
async def test_memory_filter_uses_existing_candidates(client: AsyncClient) -> None:
    from app.session import memory as session_memory

    session_id = "session_filter_test"
    session_memory.reset(session_id)
    session_memory.save_search_results(
        session_id,
        query="java",
        effective_query="java",
        candidates=[
            {"id": "1", "location": "Paris", "skills": ["Java", "Spring Boot"]},
            {"id": "2", "location": "Lyon", "skills": ["Java"]},
        ],
    )
    try:
        response = await client.post(
            "/api/chat?debug=true",
            json={"message": "Seulement en Ile-de-France", "sessionId": session_id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sessionId"] == session_id
        assert [candidate["id"] for candidate in body["candidates"]] == ["1"]
        assert body["debug"]["memoryCandidateCount"] == 1
    finally:
        session_memory.reset(session_id)


@pytest.mark.asyncio
async def test_chat_session_reset_deletes_memory(client: AsyncClient) -> None:
    from app.session import memory as session_memory

    session_id = "session_reset_test"
    session_memory.get_or_create(session_id).last_user_query = "java"

    response = await client.post(
        "/api/chat/session/reset",
        json={"sessionId": session_id},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "sessionId": session_id}
    assert session_id not in session_memory.SESSION_STORE
