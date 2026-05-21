"""Health endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok_with_mock_dependency(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]

    mcp = body["dependencies"]["mcp"]
    assert mcp["status"] == "mock"
    assert mcp["url"]
    assert mcp["transport"]
    assert mcp["error"] is None
