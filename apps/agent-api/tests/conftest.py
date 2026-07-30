"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.storage.sqlite_store import SqliteConversationStore


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> None:
    """Shield the suite from the developer's local .env.

    A real .env with ENABLE_AUTH=true would 401 every unauthenticated
    test request (auth behaviour has its own tests with explicit
    settings). Env vars take precedence over .env in pydantic-settings,
    and the cache is cleared in case get_settings() already ran at
    import time.
    """
    os.environ["ENABLE_AUTH"] = "false"
    get_settings.cache_clear()


@pytest.fixture()
def mock_mcp_client() -> MockMcpClient:
    return MockMcpClient()


@pytest_asyncio.fixture()
async def client(mock_mcp_client: MockMcpClient) -> AsyncIterator[AsyncClient]:
    """App + AsyncClient with mock MCP bound directly (lifespan bypassed)."""
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = mock_mcp_client
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    store = SqliteConversationStore(":memory:")
    await store.initialize()
    app.state.conversation_store = store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await store.close()
