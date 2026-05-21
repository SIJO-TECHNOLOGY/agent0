"""Tests for app/api/dependencies.py: no silent fallback, structured 503."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import McpClientUnavailableError, get_mcp_client
from app.main import create_app
from app.mcp.mock_client import MockMcpClient


def _request_with_state(**state: object) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


def test_get_mcp_client_returns_bound_client() -> None:
    sentinel = MockMcpClient()
    request = _request_with_state(mcp_client=sentinel)

    assert get_mcp_client(request) is sentinel  # type: ignore[arg-type]


def test_get_mcp_client_raises_when_none_bound() -> None:
    request = _request_with_state(mcp_client=None)

    with pytest.raises(McpClientUnavailableError):
        get_mcp_client(request)  # type: ignore[arg-type]


def test_get_mcp_client_raises_when_attribute_missing() -> None:
    request = _request_with_state()  # no mcp_client on state at all

    with pytest.raises(McpClientUnavailableError):
        get_mcp_client(request)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_returns_503_when_mcp_client_missing() -> None:
    # ASGITransport does not trigger lifespan, so app.state.mcp_client
    # is unset for the duration of this request.
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/search", json={"query": "consultants python"}
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "mcp_client_unavailable"
    assert "warnings" in body
