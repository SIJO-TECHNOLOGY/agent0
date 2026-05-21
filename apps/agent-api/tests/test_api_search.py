"""POST /api/search endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

REQUIRED_RESPONSE_KEYS = {
    "original_query",
    "interpreted_intent",
    "execution_plan",
    "tool_calls",
    "results",
    "summary",
    "confidence",
    "warnings",
}


@pytest.mark.asyncio
async def test_search_returns_documented_shape(client: AsyncClient) -> None:
    response = await client.post(
        "/api/search",
        json={"query": "Find senior Java consultants available next month"},
    )

    assert response.status_code == 200
    body = response.json()
    assert REQUIRED_RESPONSE_KEYS.issubset(body.keys())
    assert body["original_query"].startswith("Find senior Java consultants")
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["results"], list)
    assert isinstance(body["tool_calls"], list)
    assert len(body["tool_calls"]) >= 1
    # Mocked consultants handler always returns at least one record for
    # queries with keywords.
    assert len(body["results"]) >= 1
    assert body["interpreted_intent"]["constraints"].get("seniority") == "senior"


@pytest.mark.asyncio
async def test_search_rejects_blank_query(client: AsyncClient) -> None:
    response = await client.post("/api/search", json={"query": "   "})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_search_rejects_missing_query(client: AsyncClient) -> None:
    response = await client.post("/api/search", json={})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_search_filters_default_to_empty_object(client: AsyncClient) -> None:
    response = await client.post(
        "/api/search",
        json={"query": "consultants python"},
    )

    assert response.status_code == 200
    # Filters do not appear in the response body but the request should be
    # accepted without an explicit `filters` field.
    body = response.json()
    assert body["original_query"] == "consultants python"
