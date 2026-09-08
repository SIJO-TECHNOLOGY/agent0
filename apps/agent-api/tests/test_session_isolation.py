"""Multi-user isolation of the process-local session stores.

Two authenticated users who happen to use the same conversation id must
never share, overwrite, or reset one another's in-memory state. State is
keyed by ``SessionKey(user_oid, conversation_id)`` throughout.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.auth import AuthenticatedUser, get_current_user
from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.services import conversation_memory as memory
from app.session import memory as session_memory
from app.session.memory import SessionKey
from app.storage.sqlite_store import SqliteConversationStore

USER_A = "oid-user-a"
USER_B = "oid-user-b"
SHARED_CONV = "conv_shared"


def _clear() -> None:
    session_memory.SESSION_STORE.clear()
    memory._pools.clear()
    memory._queries.clear()


def test_same_conversation_id_two_users_get_separate_state() -> None:
    _clear()
    a = session_memory.get_or_create(USER_A, SHARED_CONV)
    b = session_memory.get_or_create(USER_B, SHARED_CONV)

    assert a is not b
    a.last_user_query = "recherche de A"
    b.last_user_query = "recherche de B"

    assert session_memory.get_or_create(USER_A, SHARED_CONV).last_user_query == "recherche de A"
    assert session_memory.get_or_create(USER_B, SHARED_CONV).last_user_query == "recherche de B"
    assert SessionKey(USER_A, SHARED_CONV) in session_memory.SESSION_STORE
    assert SessionKey(USER_B, SHARED_CONV) in session_memory.SESSION_STORE


def test_result_pools_are_isolated_per_user() -> None:
    _clear()
    memory.store_results(USER_A, SHARED_CONV, [{"id": "a1"}, {"id": "a2"}])
    memory.store_results(USER_B, SHARED_CONV, [{"id": "b1"}])

    assert [c["id"] for c in memory.next_page(USER_A, SHARED_CONV)["candidates"]] == ["a1", "a2"]
    assert [c["id"] for c in memory.next_page(USER_B, SHARED_CONV)["candidates"]] == ["b1"]


def test_reset_for_one_user_does_not_touch_another() -> None:
    _clear()
    session_memory.get_or_create(USER_A, SHARED_CONV).last_user_query = "A"
    session_memory.get_or_create(USER_B, SHARED_CONV).last_user_query = "B"
    memory.store_results(USER_A, SHARED_CONV, [{"id": "a1"}])
    memory.store_results(USER_B, SHARED_CONV, [{"id": "b1"}])

    memory.reset(USER_A, SHARED_CONV)

    # A is gone; B is untouched.
    assert SessionKey(USER_A, SHARED_CONV) not in session_memory.SESSION_STORE
    assert SessionKey(USER_B, SHARED_CONV) in session_memory.SESSION_STORE
    assert memory.has_pool(USER_B, SHARED_CONV) is True
    assert [c["id"] for c in memory.next_page(USER_B, SHARED_CONV)["candidates"]] == ["b1"]


@pytest_asyncio.fixture()
async def app_with_user() -> AsyncIterator[tuple[object, AsyncClient, dict]]:
    """App whose current user is swappable via a mutable holder."""
    _clear()
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = MockMcpClient()
    app.state.mcp_status = McpDependencyStatus(
        status="mock", url=settings.mcp_server_url,
        transport=settings.mcp_transport, error=None,
    )
    store = SqliteConversationStore(":memory:")
    await store.initialize()
    app.state.conversation_store = store

    holder = {"user": AuthenticatedUser(username="a", oid=USER_A)}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield app, ac, holder
    await store.close()
    app.dependency_overrides.clear()


async def test_user_b_cannot_reset_user_a_session_via_endpoint(app_with_user) -> None:
    _app, ac, holder = app_with_user

    # User A has a live session for the shared conversation id.
    session_memory.get_or_create(USER_A, SHARED_CONV).last_user_query = "secret de A"

    # User B calls the reset endpoint with A's conversation id.
    holder["user"] = AuthenticatedUser(username="b", oid=USER_B)
    response = await ac.post(
        "/api/chat/session/reset", json={"sessionId": SHARED_CONV}
    )

    assert response.status_code == 200
    # A's session is intact — B only cleared their own (non-existent) state.
    assert SessionKey(USER_A, SHARED_CONV) in session_memory.SESSION_STORE
    assert (
        session_memory.SESSION_STORE[SessionKey(USER_A, SHARED_CONV)].last_user_query
        == "secret de A"
    )
