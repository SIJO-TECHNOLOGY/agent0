"""End-to-end API tests for the full candidate-search orchestration.

Covers the realistic JSON:API-style `searchCandidates` payload plus
`getCandidateDetail`/`getCandidateTechnicalDocument` enrichment, and
the evidence-based ranking step.
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


SEARCH_CANDIDATES_TOOL = McpTool(
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

DETAIL_TOOL = McpTool(
    name="getCandidateDetail",
    description="Fetch candidate by id.",
    input_schema={
        "type": "object",
        "properties": {"candidateId": {"type": "integer"}},
    },
)

TECH_DOC_TOOL = McpTool(
    name="getCandidateTechnicalDocument",
    description="Fetch the candidate's technical document.",
    input_schema={
        "type": "object",
        "properties": {"candidateId": {"type": "integer"}},
    },
)


# Realistic JSON:API-style searchCandidates response: each record has
# top-level id/type with all business fields under `attributes`.
_SEARCH_RESULTS = [
    {
        "id": "41924",
        "type": "candidate",
        "attributes": {
            "firstName": "Sarah",
            "lastName": "Martin",
            "jobTitle": "Backend Java Engineer",
            "city": "Paris",
            "country": "France",
        },
    },
    {
        "id": "41925",
        "type": "candidate",
        "attributes": {
            "firstName": "Alex",
            "lastName": "Dupont",
            "jobTitle": "Java Tech Lead",
            "city": "Lyon",
        },
    },
]


_DETAIL_BY_ID: dict[int, dict[str, object]] = {
    41924: {
        "id": "41924",
        "type": "candidate",
        "attributes": {
            "firstName": "Sarah",
            "lastName": "Martin",
            "jobTitle": "Senior Backend Engineer",
            "experienceYears": 12,
            "city": "Paris",
            "country": "France",
        },
    },
    41925: {
        "id": "41925",
        "type": "candidate",
        "attributes": {
            "firstName": "Alex",
            "lastName": "Dupont",
            "jobTitle": "Java Tech Lead",
            "experienceYears": 8,
            "city": "Lyon",
            "country": "France",
        },
    },
}


_TECH_DOCS_BY_ID: dict[int, dict[str, object]] = {
    41924: {
        "candidateId": 41924,
        "skills": ["Java", "Spring", "Kafka"],
        "summary": (
            "10+ years backend engineer with deep experience on CIB "
            "(Corporate & Investment Banking) trading platforms."
        ),
    },
    41925: {
        "candidateId": 41925,
        "skills": ["Java", "Python"],
        "summary": "Polyglot tech lead with retail banking background.",
    },
}


_TOOL_CALL_LOG: list[tuple[str, dict[str, object]]] = []


async def _search_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _TOOL_CALL_LOG.append(("searchCandidates", dict(inputs)))
    return list(_SEARCH_RESULTS)


async def _detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _TOOL_CALL_LOG.append(("getCandidateDetail", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    if cid in _DETAIL_BY_ID:
        return [_DETAIL_BY_ID[cid]]
    return []


async def _tech_doc_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _TOOL_CALL_LOG.append(("getCandidateTechnicalDocument", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    if cid in _TECH_DOCS_BY_ID:
        return [_TECH_DOCS_BY_ID[cid]]
    return []


def _make_app(*, include_tech_doc: bool = True) -> object:
    tools = [SEARCH_CANDIDATES_TOOL, DETAIL_TOOL]
    handlers = {
        "searchCandidates": _search_handler,
        "getCandidateDetail": _detail_handler,
    }
    if include_tech_doc:
        tools.append(TECH_DOC_TOOL)
        handlers["getCandidateTechnicalDocument"] = _tech_doc_handler

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


@pytest_asyncio.fixture()
async def orchestration_client() -> AsyncIterator[AsyncClient]:
    _TOOL_CALL_LOG.clear()
    app = _make_app(include_tech_doc=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def orchestration_client_no_tech_doc() -> AsyncIterator[AsyncClient]:
    _TOOL_CALL_LOG.clear()
    app = _make_app(include_tech_doc=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


QUERY = (
    "search a dev who has more 10 years experience on java and his last "
    "experience should be in CIB"
)


@pytest.mark.asyncio
async def test_search_returns_real_candidate_ids_not_unknown(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )

    assert response.status_code == 200
    body = response.json()
    candidate_ids = [c["id"] for c in body["ui"]["candidates"]]
    assert candidate_ids, "expected at least one candidate"
    assert "unknown" not in candidate_ids
    assert set(candidate_ids) <= {"41924", "41925"}


@pytest.mark.asyncio
async def test_search_normalizes_full_name_from_json_api_attributes(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    body = response.json()
    full_names = {c["full_name"] for c in body["ui"]["candidates"]}
    assert "Sarah Martin" in full_names or "Alex Dupont" in full_names


@pytest.mark.asyncio
async def test_search_enriches_top_candidates_via_detail_and_tech_doc(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    assert response.status_code == 200

    tool_names = [name for name, _ in _TOOL_CALL_LOG]
    assert "searchCandidates" in tool_names
    assert tool_names.count("getCandidateDetail") >= 1
    assert tool_names.count("getCandidateTechnicalDocument") >= 1

    # getCandidateDetail must have been called with each shortlisted id.
    detail_ids = {
        int(args.get("candidateId") or args.get("id") or 0)
        for name, args in _TOOL_CALL_LOG
        if name == "getCandidateDetail"
    }
    assert detail_ids <= {41924, 41925}
    assert detail_ids  # at least one was enriched


@pytest.mark.asyncio
async def test_search_picks_evidence_rich_candidate_as_top_match(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    body = response.json()
    # Sarah's tech doc mentions both Java and CIB; Alex's mentions only Java.
    # Ranking by evidence must put Sarah first.
    assert body["ui"]["candidates"][0]["id"] == "41924"


@pytest.mark.asyncio
async def test_search_response_does_not_leak_internal_enrichment_keys(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    serialized = response.text
    assert "_enrichment_detail" not in serialized
    assert "_enrichment_technical_document" not in serialized
    # Raw MCP-style JSON:API keys must not surface either.
    assert "attributes" not in response.json()["ui"]["candidates"][0]


@pytest.mark.asyncio
async def test_search_message_still_signals_unmapped_experience_filter(
    orchestration_client: AsyncClient,
) -> None:
    response = await orchestration_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    message = response.json()["message"]
    assert "experience filter could not be applied" in message


@pytest.mark.asyncio
async def test_search_works_without_tech_doc_tool(
    orchestration_client_no_tech_doc: AsyncClient,
) -> None:
    response = await orchestration_client_no_tech_doc.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    assert response.status_code == 200
    body = response.json()
    # We must still get normalized cards with real ids.
    candidate_ids = [c["id"] for c in body["ui"]["candidates"]]
    assert candidate_ids
    assert "unknown" not in candidate_ids
    # No tech-doc calls should have been made.
    tool_names = [name for name, _ in _TOOL_CALL_LOG]
    assert "getCandidateTechnicalDocument" not in tool_names
