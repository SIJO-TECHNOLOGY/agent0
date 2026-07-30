"""Session context survives a process restart via store rehydration."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient

from app.services import conversation_memory
from app.session import memory as session_memory
from app.session.rehydrate import ensure_session_hydrated
from app.storage.sqlite_store import SqliteConversationStore

USER = "user-1"
OTHER = "user-2"


@pytest_asyncio.fixture()
async def store() -> AsyncIterator[SqliteConversationStore]:
    instance = SqliteConversationStore(":memory:")
    await instance.initialize()
    yield instance
    await instance.close()


def _simulate_restart() -> None:
    """Forget every in-process session, as a real restart would."""
    session_memory.SESSION_STORE.clear()
    conversation_memory._pools.clear()
    conversation_memory._queries.clear()


async def test_hydration_restores_context_and_candidates(store) -> None:
    await store.record_turn(
        USER,
        "conv_1",
        user_message="développeur java",
        assistant_message="2 candidats trouvés.",
        assistant_ui={
            "type": "candidate_cards",
            "candidates": [{"id": "c1"}, {"id": "c2"}],
        },
        context={
            "currentSearch": {
                "query": "développeur java",
                "effectiveQuery": "développeur java",
                "page": 2,
                "seenIds": ["c1", "c2"],
            },
            "lastFilters": {"location": "Ile-de-France"},
        },
    )
    _simulate_restart()

    await ensure_session_hydrated(store, USER, "conv_1")

    session = session_memory.SESSION_STORE["conv_1"]
    assert session.current_search["effectiveQuery"] == "développeur java"
    assert session.current_search["page"] == 2
    assert session.current_search["seenIds"] == ["c1", "c2"]
    assert session.last_filters == {"location": "Ile-de-France"}
    assert [c["id"] for c in session.current_candidates] == ["c1", "c2"]
    assert session.last_user_query == "développeur java"
    assert len(session.messages) == 2


async def test_hydration_scoped_to_owner(store) -> None:
    await store.record_turn(
        USER, "conv_1", user_message="secret", assistant_message="ok"
    )
    _simulate_restart()
    await ensure_session_hydrated(store, OTHER, "conv_1")
    assert "conv_1" not in session_memory.SESSION_STORE


async def test_hydration_skips_live_sessions(store) -> None:
    await store.record_turn(
        USER, "conv_1", user_message="ancienne requête", assistant_message="ok",
        context={"currentSearch": {"page": 5}},
    )
    _simulate_restart()
    live = session_memory.get_or_create("conv_1")
    live.current_search = {"page": 1}

    await ensure_session_hydrated(store, USER, "conv_1")
    # The live session wins: no overwrite from the store.
    assert session_memory.SESSION_STORE["conv_1"].current_search == {"page": 1}


async def test_hydration_without_store_is_noop() -> None:
    _simulate_restart()
    await ensure_session_hydrated(None, USER, "conv_1")
    assert "conv_1" not in session_memory.SESSION_STORE


async def _run_stream(client: AsyncClient, query: str, conversation_id: str | None = None) -> str:
    payload: dict[str, object] = {"query": query}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    async with client.stream("POST", "/api/search/stream", json=payload) as response:
        assert response.status_code == 200
        return "".join([chunk async for chunk in response.aiter_text()])


async def test_more_continues_after_restart(client: AsyncClient) -> None:
    body = await _run_stream(client, "développeur java expérimenté")
    assert "final_response" in body
    conversations = (await client.get("/api/conversations")).json()
    conversation_id = conversations[0]["id"]
    original = dict(
        session_memory.SESSION_STORE[conversation_id].current_search
    )
    assert original.get("page") == 1

    _simulate_restart()

    body = await _run_stream(client, "d'autres profils", conversation_id)
    assert "final_response" in body
    restored = session_memory.SESSION_STORE[conversation_id].current_search
    # The follow-up continued the SAME search on the provider's next page
    # instead of starting a fresh one from "d'autres profils".
    assert restored.get("page") == 2
    assert restored.get("effectiveQuery") == original.get("effectiveQuery")


async def test_filter_uses_restored_candidates_after_restart(
    client: AsyncClient,
) -> None:
    body = await _run_stream(client, "développeur java expérimenté")
    assert "final_response" in body
    conversation_id = (await client.get("/api/conversations")).json()[0]["id"]

    _simulate_restart()

    body = await _run_stream(
        client, "seulement les disponibles", conversation_id
    )
    # Served from the restored in-memory pool, without a new MCP search.
    assert '"planner_mode": "memory"' in body
