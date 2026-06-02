"""End-to-end POST /api/search tests for the candidate-search flow.

Exercises the real-tool name (`searchCandidates`) against a stubbed
MCP client so we can prove planner -> selector -> mapper resolves
correctly without touching BoondManager.
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


SEARCH_CANDIDATES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "keywords": {"type": "string"},
        "page": {"type": "integer"},
        "numberPerPage": {"type": "integer"},
    },
}


def _search_candidates_tool() -> McpTool:
    return McpTool(
        name="searchCandidates",
        description="Search candidates in BoondManager.",
        input_schema=SEARCH_CANDIDATES_SCHEMA,
    )


async def _two_results_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    # The handler captures the call shape so the test can assert it.
    _captured_inputs.append(dict(inputs))
    return [
        {
            "id": 1001,
            "firstName": "Sarah",
            "lastName": "Martin",
            "jobTitle": "Backend Java Engineer",
            "city": "Paris",
            "country": "France",
            "experienceYears": 12,
            "skills": ["Java", "Spring"],
        },
        {
            "id": 1002,
            "firstName": "Alex",
            "lastName": "Dupont",
            "jobTitle": "Java Tech Lead",
            "city": "Lyon",
            "skills": ["Java", "CIB"],
        },
    ]


async def _empty_handler(_inputs: dict[str, object]) -> list[dict[str, object]]:
    _captured_inputs.append(dict(_inputs))
    return []


async def _java_only_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    # Neither candidate carries any "CIB" signal, so that criterion can
    # never be verified from search data.
    _captured_inputs.append(dict(inputs))
    return [
        {
            "id": 2001,
            "firstName": "Jo",
            "lastName": "Engs",
            "jobTitle": "Java Engineer",
            "skills": ["Java", "Spring"],
        },
        {
            "id": 2002,
            "firstName": "Mo",
            "lastName": "Coder",
            "jobTitle": "C# Developer",
            "skills": ["C#"],
        },
    ]


_captured_inputs: list[dict[str, object]] = []


def _make_app(handler) -> AsyncClient:
    mcp_client = MockMcpClient(
        tools=[_search_candidates_tool()],
        handlers={"searchCandidates": handler},
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
    return app


@pytest_asyncio.fixture()
async def candidate_search_client() -> AsyncIterator[AsyncClient]:
    _captured_inputs.clear()
    app = _make_app(_two_results_handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def empty_candidate_search_client() -> AsyncIterator[AsyncClient]:
    _captured_inputs.clear()
    app = _make_app(_empty_handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def java_only_candidate_search_client() -> AsyncIterator[AsyncClient]:
    _captured_inputs.clear()
    app = _make_app(_java_only_handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


CANDIDATE_SEARCH_QUERY = (
    "search a dev who has more 10 years experience on java and his last "
    "experience should be in CIB"
)


@pytest.mark.asyncio
async def test_candidate_search_calls_search_candidates_with_string_keywords(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search",
        json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
    )

    assert response.status_code == 200
    # The real MCP tool must have been called (not the legacy mock name).
    assert len(_captured_inputs) == 1
    inputs = _captured_inputs[0]
    # keywords must be a string per the real MCP schema.
    assert isinstance(inputs["keywords"], str)
    keywords_value = str(inputs["keywords"]).lower()
    assert "java" in keywords_value
    assert "cib" in keywords_value
    # page / numberPerPage defaults injected when schema accepts them.
    assert inputs["page"] == 1
    assert inputs["numberPerPage"] == 25


@pytest.mark.asyncio
async def test_candidate_search_normalizes_results_into_cards(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search",
        json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"
    assert len(body["ui"]["candidates"]) == 2

    # This test validates normalization, not ranking, so look the card up by
    # id rather than position. (Evidence ranking now puts the candidate that
    # matches more criteria first — covered by a dedicated ranking test.)
    sarah = next(c for c in body["ui"]["candidates"] if c["id"] == "1001")
    # Cards are mapped, raw MCP fields never leak.
    assert sarah["full_name"] == "Sarah Martin"
    assert sarah["title"] == "Backend Java Engineer"
    assert sarah["location"] == "Paris, France"
    assert sarah["skills"] == ["Java", "Spring"]
    assert "firstName" not in response.text
    assert "lastName" not in response.text


@pytest.mark.asyncio
async def test_unverifiable_criteria_yields_honest_broad_message(
    java_only_candidate_search_client: AsyncClient,
) -> None:
    response = await java_only_candidate_search_client.post(
        "/api/search",
        json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
    )

    assert response.status_code == 200
    body = response.json()
    cards = body["ui"]["candidates"]
    # No candidate is dropped — broad results are kept, just framed honestly.
    assert len(cards) == 2

    message = body["message"]
    # Must NOT over-claim that the candidates match the strict criteria.
    assert "correspondant à votre recherche" not in message
    assert "profils proches de votre recherche" in message
    assert "restent à confirmer" in message
    assert "critères stricts" not in message
    assert "non vérifié" not in message

    # The contradicting C# candidate must not read as a confident match.
    csharp = next(c for c in cards if c["id"] == "2002")
    assert csharp["match_score"] is None


@pytest.mark.asyncio
async def test_candidate_search_message_mentions_limited_search(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search",
        json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
    )

    assert response.status_code == 200
    message = response.json()["message"]
    # 10 years experience could not be mapped to an MCP dictionary id,
    # so the message must say so rather than hide the limitation.
    assert "filtre d'expérience non appliqué" in message


@pytest.mark.asyncio
async def test_candidate_search_empty_results_returns_clear_message(
    empty_candidate_search_client: AsyncClient,
) -> None:
    response = await empty_candidate_search_client.post(
        "/api/search",
        json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["candidates"] == []
    # Empty MCP results must say "no candidates matched", not a planner
    # failure message — but the experience-filter hint still surfaces.
    assert "Aucun candidat" in body["message"]
    assert "filtre d'expérience non appliqué" in body["message"]


@pytest.mark.asyncio
async def test_candidate_search_with_no_available_tool_is_not_hidden() -> None:
    # MCP client without searchCandidates and without the legacy mock
    # tool — the planner cannot satisfy the request.
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = MockMcpClient(tools=[])
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/search",
            json={"query": CANDIDATE_SEARCH_QUERY, "filters": {}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["candidates"] == []
    assert "La recherche n'a pas pu être lancée" in body["message"]
