"""End-to-end LLM planner flow tests against POST /api/search.

A fake ``LlmPlanner`` is injected into ``app.state.llm_planner`` so we
exercise the full LLM graph (discover → plan → execute with fan-out →
rank → respond) without any network or real LLM SDK.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.models.intent import LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool
from app.services.llm_planner import (
    LlmPlannerError,
    PlannerConstraints,
    validate_plan,
)


# ----- mock MCP tools the fake planner is allowed to plan against ---------

SEARCH_TOOL = McpTool(
    name="searchCandidates",
    description="Search candidates by keyword string.",
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
        "required": ["candidateId"],
    },
)

TECH_DOC_TOOL = McpTool(
    name="getCandidateTechnicalDocument",
    description="Fetch the candidate's technical document.",
    input_schema={
        "type": "object",
        "properties": {"candidateId": {"type": "integer"}},
        "required": ["candidateId"],
    },
)

DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Fetch a BoondManager dictionary.",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
    },
)


_SEARCH_RECORDS = [
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
            "typeOf": 2,
        },
    },
    41925: {
        "id": "41925",
        "type": "candidate",
        "attributes": {
            "firstName": "Alex",
            "lastName": "Dupont",
            "experienceYears": 8,
        },
    },
}


_TECH_DOCS_BY_ID: dict[int, dict[str, object]] = {
    41924: {
        "candidateId": 41924,
        "skills": ["Java", "Spring", "Kafka"],
        "summary": "10+ years backend on CIB platforms.",
    },
    41925: {
        "candidateId": 41925,
        "skills": ["Java"],
        "summary": "Retail banking background.",
    },
}


# Records every MCP call across all fixtures in this module.
_calls: list[tuple[str, dict]] = []


async def _search_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _calls.append(("searchCandidates", dict(inputs)))
    return list(_SEARCH_RECORDS)


async def _empty_search_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _calls.append(("searchCandidates", dict(inputs)))
    return []


async def _detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _calls.append(("getCandidateDetail", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    record = _DETAIL_BY_ID.get(cid)
    return [record] if record is not None else []


async def _tech_doc_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _calls.append(("getCandidateTechnicalDocument", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    record = _TECH_DOCS_BY_ID.get(cid)
    return [record] if record is not None else []


async def _dictionary_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _calls.append(("getDictionary", dict(inputs)))
    return [
        {
            "setting": {
                "typeOf": {
                    "contract": [
                        {"id": 2, "label": "CDI"},
                        {"id": 3, "label": "Freelance"},
                    ]
                }
            }
        }
    ]


# ----- fake LLM planner ----------------------------------------------------


@dataclass
class FakeLlmPlanner:
    """A planner that returns a canned plan, validated like the real one."""

    canned_plan: LlmToolPlan
    received_query: str = ""
    received_tools: tuple[str, ...] = ()

    async def plan(
        self,
        *,
        query: str,
        filters: dict[str, object],
        tools,
        constraints: PlannerConstraints,
        emitter=None,  # accept the new optional emitter kwarg
    ):
        self.received_query = query
        self.received_tools = tuple(t.name for t in tools)
        # Run the production validator so tests catch mismatches too.
        return validate_plan(self.canned_plan, list(tools), constraints)


@dataclass
class ExplodingLlmPlanner:
    """Planner that always raises — used to exercise the warning path."""

    error: str = "synthetic LLM failure"

    async def plan(self, **_kwargs):
        raise LlmPlannerError(self.error)


# ----- app + fixture wiring ------------------------------------------------


def _make_app(*, planner, mcp_tools, handlers) -> object:
    mcp_client = MockMcpClient(tools=mcp_tools, handlers=handlers)
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = mcp_client
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    app.state.llm_planner = planner
    return app


def _candidate_search_plan() -> LlmToolPlan:
    return LlmToolPlan(
        interpreted_intent={"objective": "candidate_search"},
        plan=[
            PlannedToolCall(
                tool_name="searchCandidates",
                inputs={
                    "keywords": "+java CIB",
                    "page": 1,
                    "numberPerPage": 10,
                },
            ),
            PlannedToolCall(
                tool_name="getCandidateDetail",
                inputs={},
                depends_on="searchCandidates",
                result_selector="candidate_ids",
            ),
            PlannedToolCall(
                tool_name="getCandidateTechnicalDocument",
                inputs={},
                depends_on="searchCandidates",
                result_selector="candidate_ids",
            ),
        ],
    )


def _detail_only_plan() -> LlmToolPlan:
    return LlmToolPlan(
        interpreted_intent={"objective": "candidate_detail"},
        plan=[
            PlannedToolCall(
                tool_name="getCandidateDetail",
                inputs={"candidateId": 41924},
            )
        ],
    )


def _invalid_plan() -> LlmToolPlan:
    # Tool name that does NOT exist in our discovered tool list.
    return LlmToolPlan(
        plan=[PlannedToolCall(tool_name="__nonexistent_tool__")]
    )


@pytest_asyncio.fixture()
async def candidate_search_client() -> AsyncIterator[AsyncClient]:
    _calls.clear()
    planner = FakeLlmPlanner(canned_plan=_candidate_search_plan())
    app = _make_app(
        planner=planner,
        mcp_tools=[SEARCH_TOOL, DETAIL_TOOL, TECH_DOC_TOOL, DICTIONARY_TOOL],
        handlers={
            "searchCandidates": _search_handler,
            "getCandidateDetail": _detail_handler,
            "getCandidateTechnicalDocument": _tech_doc_handler,
            "getDictionary": _dictionary_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def detail_only_client() -> AsyncIterator[AsyncClient]:
    _calls.clear()
    planner = FakeLlmPlanner(canned_plan=_detail_only_plan())
    app = _make_app(
        planner=planner,
        mcp_tools=[DETAIL_TOOL],
        handlers={"getCandidateDetail": _detail_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def invalid_plan_client() -> AsyncIterator[AsyncClient]:
    _calls.clear()
    planner = FakeLlmPlanner(canned_plan=_invalid_plan())
    app = _make_app(
        planner=planner,
        mcp_tools=[SEARCH_TOOL],
        handlers={"searchCandidates": _search_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def exploding_planner_client() -> AsyncIterator[AsyncClient]:
    _calls.clear()
    planner = ExplodingLlmPlanner()
    app = _make_app(
        planner=planner,
        mcp_tools=[SEARCH_TOOL],
        handlers={"searchCandidates": _search_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def empty_search_llm_client() -> AsyncIterator[AsyncClient]:
    _calls.clear()
    planner = FakeLlmPlanner(canned_plan=_candidate_search_plan())
    app = _make_app(
        planner=planner,
        mcp_tools=[SEARCH_TOOL, DETAIL_TOOL, TECH_DOC_TOOL],
        handlers={
            "searchCandidates": _empty_search_handler,
            "getCandidateDetail": _detail_handler,
            "getCandidateTechnicalDocument": _tech_doc_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ----- tests ---------------------------------------------------------------


QUERY_FUZZY = (
    "search a dev who has more 10 years experience on java and his last "
    "experience should be in CIB"
)


@pytest.mark.asyncio
async def test_llm_flow_calls_tools_in_planned_order(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    assert response.status_code == 200

    # getDictionary may run first: the Agent API resolves the (backfilled)
    # years-of-experience constraint into a search filter before searching.
    tool_sequence = [name for name, _ in _calls if name != "getDictionary"]
    # searchCandidates first, then evidence enrichment via the technical
    # document. getCandidateDetail may run later for display-only fields.
    assert tool_sequence[0] == "searchCandidates"
    assert "getCandidateTechnicalDocument" in tool_sequence


@pytest.mark.asyncio
async def test_llm_flow_passes_string_keywords_to_search(
    candidate_search_client: AsyncClient,
) -> None:
    await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    search_calls = [args for name, args in _calls if name == "searchCandidates"]
    assert search_calls
    kw = search_calls[0]["keywords"]
    assert isinstance(kw, str)
    assert "java" in kw.lower()
    assert "cib" in kw.lower()


@pytest.mark.asyncio
async def test_llm_flow_fans_out_tech_doc_calls_per_candidate(
    candidate_search_client: AsyncClient,
) -> None:
    await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    tech_ids = {
        int(args.get("candidateId") or args.get("id") or 0)
        for name, args in _calls
        if name == "getCandidateTechnicalDocument"
    }
    assert tech_ids == {41924, 41925}
    detail_ids = {
        int(args.get("candidateId") or args.get("id") or 0)
        for name, args in _calls
        if name == "getCandidateDetail"
    }
    assert detail_ids == {41924, 41925}


@pytest.mark.asyncio
async def test_llm_flow_resolves_contract_from_candidate_detail(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    assert response.status_code == 200

    candidates = response.json()["ui"]["candidates"]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    assert by_id["41924"]["contract_preferences"] == ["CDI"]


@pytest.mark.asyncio
async def test_llm_flow_respects_max_enrichments_cap(
    candidate_search_client: AsyncClient,
) -> None:
    await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    # Default max_enrichments=5; only 2 search results exist so we expect 2
    # technical-document enrichment calls.
    tech_count = sum(
        1 for name, _ in _calls if name == "getCandidateTechnicalDocument"
    )
    assert tech_count <= 5
    assert tech_count == 2


@pytest.mark.asyncio
async def test_llm_flow_returns_normalized_candidate_cards(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"
    ids = {c["id"] for c in body["ui"]["candidates"]}
    # QUERY_FUZZY asks for 10+ years. The backfilled seniority constraint is
    # the only rankable criterion of this canned intent, so 41925 (no
    # experience evidence anywhere) scores zero and is dropped while 41924
    # ("10+ years" in its tech doc) is kept — empty dossiers no longer ride
    # along at the top.
    assert ids == {"41924"}


@pytest.mark.asyncio
async def test_llm_flow_does_not_leak_raw_mcp_or_enrichment_keys(
    candidate_search_client: AsyncClient,
) -> None:
    response = await candidate_search_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    body = response.json()
    serialized = response.text
    assert "_enrichment_detail" not in serialized
    assert "_enrichment_technical_document" not in serialized
    assert "attributes" not in body["ui"]["candidates"][0]
    assert "firstName" not in serialized
    assert "lastName" not in serialized


@pytest.mark.asyncio
async def test_llm_flow_handles_direct_candidate_detail_query(
    detail_only_client: AsyncClient,
) -> None:
    response = await detail_only_client.post(
        "/api/search",
        json={
            "query": "Find the candidate information with candidate id 41924",
            "filters": {},
        },
    )
    assert response.status_code == 200
    # Only getCandidateDetail was called, with candidateId=41924.
    assert _calls == [("getCandidateDetail", {"candidateId": 41924})]
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"
    assert len(body["ui"]["candidates"]) == 1
    assert body["ui"]["candidates"][0]["id"] == "41924"


@pytest.mark.asyncio
async def test_llm_invalid_plan_does_not_call_any_mcp_tool(
    invalid_plan_client: AsyncClient,
) -> None:
    response = await invalid_plan_client.post(
        "/api/search", json={"query": "anything", "filters": {}}
    )
    assert response.status_code == 200
    assert _calls == []
    body = response.json()
    assert body["ui"]["candidates"] == []


@pytest.mark.asyncio
async def test_llm_planner_failure_surfaces_user_safe_message(
    exploding_planner_client: AsyncClient,
) -> None:
    response = await exploding_planner_client.post(
        "/api/search", json={"query": "anything", "filters": {}}
    )
    assert response.status_code == 200
    assert _calls == []
    # Public response must NOT leak the exception text.
    body = response.json()
    assert "synthetic LLM failure" not in response.text
    assert body["ui"]["candidates"] == []


@pytest.mark.asyncio
async def test_llm_empty_search_does_not_break_response_contract(
    empty_search_llm_client: AsyncClient,
) -> None:
    response = await empty_search_llm_client.post(
        "/api/search", json={"query": QUERY_FUZZY, "filters": {}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ui"]["type"] == "candidate_cards"
    assert body["ui"]["candidates"] == []
    # Fan-out steps were skipped because depends_on produced no ids;
    # only the searchCandidates call should have been issued.
    assert all(name == "searchCandidates" for name, _ in _calls)
