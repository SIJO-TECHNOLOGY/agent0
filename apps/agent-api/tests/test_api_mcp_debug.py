"""Tests for the dev-only POST /api/mcp/tools/{tool_name}/call endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_mcp_client
from app.config import Settings, get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus


def _seed_app(*, debug_enabled: bool) -> tuple[object, MockMcpClient]:
    mcp_client = MockMcpClient()

    base_settings = Settings(use_mock_mcp=True)
    settings = base_settings.model_copy(
        update={"enable_mcp_debug_endpoints": debug_enabled}
    )

    app = create_app()
    app.state.mcp_client = mcp_client
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    # Override the per-request settings dependency so the gate flips
    # without touching the lru_cache on get_settings().
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_mcp_client] = lambda: mcp_client
    return app, mcp_client


@pytest_asyncio.fixture()
async def disabled_client() -> AsyncIterator[AsyncClient]:
    app, _ = _seed_app(debug_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def enabled_client() -> AsyncIterator[AsyncClient]:
    app, _ = _seed_app(debug_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_debug_endpoint_is_disabled_by_default(
    disabled_client: AsyncClient,
) -> None:
    response = await disabled_client.post(
        "/api/mcp/tools/search_consultants/call",
        json={"inputs": {"keywords": ["java"]}},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_debug_endpoint_invokes_mcp_when_enabled(
    enabled_client: AsyncClient,
) -> None:
    response = await enabled_client.post(
        "/api/mcp/tools/search_consultants/call",
        json={"inputs": {"keywords": ["java"]}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool"] == "search_consultants"
    assert body["inputs"] == {"keywords": ["java"]}
    assert isinstance(body["records"], list)
    assert body["record_count"] == len(body["records"])
    assert body["record_count"] >= 1


@pytest.mark.asyncio
async def test_debug_endpoint_rejects_unknown_extra_request_fields(
    enabled_client: AsyncClient,
) -> None:
    response = await enabled_client.post(
        "/api/mcp/tools/search_consultants/call",
        json={"inputs": {}, "extra": "nope"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_debug_endpoint_returns_502_on_tool_error(
    enabled_client: AsyncClient,
) -> None:
    response = await enabled_client.post(
        "/api/mcp/tools/__definitely_unknown__/call",
        json={"inputs": {}},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "mcp_tool_error"
