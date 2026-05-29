"""End-to-end POST /api/search test for candidate detail lookups.

Uses a custom-tools MockMcpClient to simulate the real
`getCandidateDetail` tool so we can prove the UI mapper hides raw
MCP fields and exposes only the documented candidate-card shape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.models.tools import McpTool


async def _get_candidate_detail(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "id": inputs.get("candidateId") or inputs.get("id"),
            "firstName": "Sarah",
            "lastName": "Martin",
            "jobTitle": "Backend Java Engineer",
            "city": "Paris",
            "country": "France",
            "availability": "Available immediately",
            "experienceYears": 7,
            "skills": ["Java", "Spring", "Kafka"],
            "internalSecretField": "should_not_leak",
        }
    ]


@pytest_asyncio.fixture()
async def candidate_detail_client() -> AsyncIterator[AsyncClient]:
    tool = McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
            "required": ["candidateId"],
        },
    )
    mcp_client = MockMcpClient(
        tools=[tool],
        handlers={"getCandidateDetail": _get_candidate_detail},
    )
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = mcp_client
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_candidate_detail_lookup_returns_normalized_card(
    candidate_detail_client: AsyncClient,
) -> None:
    response = await candidate_detail_client.post(
        "/api/search",
        json={
            "query": "Find the candidate information with candidate id 41924",
            "filters": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"
    assert len(body["ui"]["candidates"]) == 1

    card = body["ui"]["candidates"][0]
    assert card["id"] == "41924"
    assert card["full_name"] == "Sarah Martin"
    assert card["title"] == "Backend Java Engineer"
    assert card["experience_years"] == 7.0
    assert card["location"] == "Paris, France"
    assert card["availability"] == "Available immediately"
    assert card["skills"] == ["Java", "Spring", "Kafka"]
    assert card["match_score"] is None  # detail lookups carry no relevance score
    assert card["boond_url"] is None
    assert isinstance(card["summary"], str) and card["summary"]


@pytest.mark.asyncio
async def test_candidate_detail_response_hides_raw_mcp_fields(
    candidate_detail_client: AsyncClient,
) -> None:
    response = await candidate_detail_client.post(
        "/api/search",
        json={
            "query": "Find the candidate information with candidate id 41924",
            "filters": {},
        },
    )

    assert response.status_code == 200
    serialized = response.text
    # Raw MCP-specific fields and any internal payload key must never
    # appear in the public response.
    assert "internalSecretField" not in serialized
    assert "firstName" not in serialized
    assert "lastName" not in serialized
    assert "jobTitle" not in serialized
    assert "data" not in response.json()["ui"]["candidates"][0]
