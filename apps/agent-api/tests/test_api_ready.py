"""Readiness endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus


def _seed_app(status: str, *, error: str | None = None):
    app = create_app()
    settings = get_settings()
    if status in {"mock", "connected"}:
        app.state.mcp_client = MockMcpClient()
    else:
        app.state.mcp_client = None
    app.state.mcp_status = McpDependencyStatus(
        status=status,  # type: ignore[arg-type]
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=error,
    )
    return app


@pytest.mark.asyncio
async def test_ready_returns_200_in_mock_mode(client: AsyncClient) -> None:
    response = await client.get("/api/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["dependencies"]["mcp"]["status"] == "mock"


@pytest.mark.asyncio
async def test_ready_returns_200_when_real_client_connected() -> None:
    app = _seed_app("connected")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["dependencies"]["mcp"]["status"] == "connected"
    assert body["dependencies"]["mcp"]["error"] is None


@pytest.mark.asyncio
async def test_ready_returns_503_when_mcp_unavailable() -> None:
    app = _seed_app("unavailable", error="McpTransientError: server down")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/ready")

    assert response.status_code == 503
    body = response.json()
    mcp = body["dependencies"]["mcp"]
    assert mcp["status"] == "unavailable"
    assert "server down" in mcp["error"]
    assert body["status"] == "unavailable"


@pytest.mark.asyncio
async def test_search_returns_503_when_mcp_unavailable() -> None:
    """End-to-end: real mode + unavailable -> /api/search returns 503."""
    app = _seed_app("unavailable", error="McpTransientError: server down")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/search", json={"query": "consultants python"}
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "mcp_client_unavailable"
