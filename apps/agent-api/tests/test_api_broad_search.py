"""End-to-end tests for broad-search guardrails and dictionary mapping."""

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


def _make_app(*, tools, handlers) -> object:
    mcp_client = MockMcpClient(tools=tools, handlers=handlers)
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


SEARCH_TOOL_WITH_EXPERIENCE = McpTool(
    name="searchCandidates",
    description="Search candidates.",
    input_schema={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "experience": {"type": "string"},
            "page": {"type": "integer"},
            "numberPerPage": {"type": "integer"},
        },
    },
)

SEARCH_TOOL_NO_EXPERIENCE = McpTool(
    name="searchCandidates",
    description="Search candidates.",
    input_schema={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "page": {"type": "integer"},
            "numberPerPage": {"type": "integer"},
        },
    },
)

DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Fetch a BoondManager dictionary.",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    },
)


_calls: list[tuple[str, dict]] = []


async def _search_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _calls.append(("searchCandidates", dict(inputs)))
    return []


async def _dict_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _calls.append(("getDictionary", dict(inputs)))
    if inputs.get("key") in {"experience", "experiences", "experienceLevel"}:
        return [
            {"id": "exp-1", "label": "0-2 years"},
            {"id": "exp-2", "label": "2-5 years"},
            {"id": "exp-3", "label": "5-10 years"},
            {"id": "exp-4", "label": "10+ years"},
        ]
    return []


async def _empty_dict_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _calls.append(("getDictionary", dict(inputs)))
    return [
        {"id": "lvl-junior", "label": "Junior"},
        {"id": "lvl-senior", "label": "Senior"},
    ]


@pytest_asyncio.fixture()
async def no_dict_client() -> AsyncIterator[AsyncClient]:
    """searchCandidates available but no getDictionary."""
    _calls.clear()
    app = _make_app(
        tools=[SEARCH_TOOL_NO_EXPERIENCE],
        handlers={"searchCandidates": _search_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def dict_client() -> AsyncIterator[AsyncClient]:
    """searchCandidates + getDictionary, dictionary has 10+ years entry."""
    _calls.clear()
    app = _make_app(
        tools=[SEARCH_TOOL_WITH_EXPERIENCE, DICTIONARY_TOOL],
        handlers={
            "searchCandidates": _search_handler,
            "getDictionary": _dict_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def dict_no_numeric_client() -> AsyncIterator[AsyncClient]:
    """getDictionary present but no entry has a numeric threshold."""
    _calls.clear()
    app = _make_app(
        tools=[SEARCH_TOOL_WITH_EXPERIENCE, DICTIONARY_TOOL],
        handlers={
            "searchCandidates": _search_handler,
            "getDictionary": _empty_dict_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


BROAD_QUERY = "search a dev who has more 10 years experience"
KEYWORD_QUERY = (
    "search a dev who has more 10 years experience on java and his last "
    "experience should be in CIB"
)


@pytest.mark.asyncio
async def test_broad_query_does_not_call_search_with_empty_criteria(
    no_dict_client: AsyncClient,
) -> None:
    response = await no_dict_client.post(
        "/api/search", json={"query": BROAD_QUERY, "filters": {}}
    )
    assert response.status_code == 200
    # No real keywords + no resolvable filter → must NOT call searchCandidates.
    assert all(name != "searchCandidates" for name, _ in _calls)


@pytest.mark.asyncio
async def test_broad_query_returns_clarification_message(
    no_dict_client: AsyncClient,
) -> None:
    response = await no_dict_client.post(
        "/api/search", json={"query": BROAD_QUERY, "filters": {}}
    )
    body = response.json()
    assert body["ui"]["candidates"] == []
    assert "Please refine your search" in body["message"]


@pytest.mark.asyncio
async def test_keyword_query_still_calls_search_with_keywords(
    no_dict_client: AsyncClient,
) -> None:
    response = await no_dict_client.post(
        "/api/search", json={"query": KEYWORD_QUERY, "filters": {}}
    )
    assert response.status_code == 200
    search_calls = [args for name, args in _calls if name == "searchCandidates"]
    # Bounded replan may invoke searchCandidates a second time with the
    # same arguments; we care that it was called with java+CIB at least
    # once and never with empty inputs.
    assert search_calls, "searchCandidates was never called"
    for args in search_calls:
        keywords = str(args.get("keywords", "")).lower()
        assert "java" in keywords
        assert "cib" in keywords


@pytest.mark.asyncio
async def test_broad_query_uses_dictionary_when_mappable(
    dict_client: AsyncClient,
) -> None:
    response = await dict_client.post(
        "/api/search", json={"query": BROAD_QUERY, "filters": {}}
    )
    assert response.status_code == 200
    # getDictionary should have been consulted at least once.
    assert any(name == "getDictionary" for name, _ in _calls)
    search_calls = [args for name, args in _calls if name == "searchCandidates"]
    assert search_calls, "searchCandidates was never called"
    # The resolver picks "10+ years" → exp-4 for the experience field.
    for args in search_calls:
        assert args.get("experience") == "exp-4"


@pytest.mark.asyncio
async def test_broad_query_clarifies_when_dictionary_has_no_numeric_entry(
    dict_no_numeric_client: AsyncClient,
) -> None:
    response = await dict_no_numeric_client.post(
        "/api/search", json={"query": BROAD_QUERY, "filters": {}}
    )
    body = response.json()
    # No mappable filter + no keyword → don't run searchCandidates.
    assert all(name != "searchCandidates" for name, _ in _calls)
    assert "Please refine your search" in body["message"]
