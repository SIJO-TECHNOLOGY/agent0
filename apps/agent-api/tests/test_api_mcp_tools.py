"""Tests for GET /api/mcp/tools."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.client import McpTransientError
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.models.tools import McpTool


@pytest.mark.asyncio
async def test_list_tools_returns_mock_catalogue(client: AsyncClient) -> None:
    response = await client.get("/api/mcp/tools")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["tools"], list)
    assert body["count"] == len(body["tools"])
    assert body["count"] >= 1

    names = {tool["name"] for tool in body["tools"]}
    assert "search_consultants" in names

    for tool in body["tools"]:
        assert set(tool.keys()) == {"name", "description", "input_schema"}
        assert isinstance(tool["name"], str) and tool["name"]
        assert isinstance(tool["description"], str)
        assert isinstance(tool["input_schema"], dict)


@pytest.mark.asyncio
async def test_list_tools_returns_503_when_client_unavailable() -> None:
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = None
    app.state.mcp_status = McpDependencyStatus(
        status="unavailable",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error="McpTransientError: server down",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/mcp/tools")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "mcp_client_unavailable"


@pytest.mark.asyncio
async def test_list_tools_returns_503_when_discovery_transient_fails() -> None:
    class FailingDiscoveryClient(MockMcpClient):
        async def discover_tools(self) -> list[McpTool]:
            raise McpTransientError("upstream MCP server unreachable")

    app = create_app()
    settings = get_settings()
    app.state.mcp_client = FailingDiscoveryClient()
    app.state.mcp_status = McpDependencyStatus(
        status="connected",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/mcp/tools")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "mcp_client_unavailable"


@pytest.mark.asyncio
async def test_list_tools_response_includes_required_fields(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/mcp/tools")

    assert response.status_code == 200
    body = response.json()
    assert "tools" in body and "count" in body
    assert all(
        {"name", "description", "input_schema"}.issubset(tool.keys())
        for tool in body["tools"]
    )
