"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
