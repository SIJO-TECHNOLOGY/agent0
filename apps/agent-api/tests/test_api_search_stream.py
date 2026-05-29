"""Tests for POST /api/search/stream Server-Sent Events surface."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.models.intent import LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool
from app.services.llm_planner import PlannerConstraints, validate_plan


# ---------- MCP tool fixtures ----------------------------------------------

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
]


async def _search_handler(_: dict[str, object]) -> list[dict[str, object]]:
    return list(_SEARCH_RECORDS)


async def _empty_search_handler(_: dict[str, object]) -> list[dict[str, object]]:
    return []


async def _detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    return [
        {
            "id": str(cid),
            "type": "candidate",
            "attributes": {
                "firstName": "Sarah",
                "lastName": "Martin",
                "experienceYears": 12,
            },
        }
    ]


# ---------- Fake LLM planner ----------------------------------------------


@dataclass
class FakeLlmPlanner:
    canned_plan: LlmToolPlan

    async def plan(
        self,
        *,
        query: str,
        filters: dict[str, object],
        tools,
        constraints: PlannerConstraints,
        emitter=None,
    ):
        validated = validate_plan(self.canned_plan, list(tools), constraints)
        # Mirror StructuredLlmPlanner's emission contract so the
        # streaming tests see plan_created + plan_validated events.
        if emitter is not None:
            await emitter.emit(
                "plan_created",
                {
                    "plan": [
                        {
                            "step": i,
                            "tool_name": s.tool_name,
                            "reason": s.reason,
                            "inputs": dict(s.inputs),
                            "depends_on": s.depends_on,
                            "result_selector": s.result_selector,
                        }
                        for i, s in enumerate(self.canned_plan.plan, start=1)
                    ],
                    "assumptions": [],
                    "warnings": [],
                },
            )
            await emitter.emit(
                "plan_validated",
                {
                    "accepted_steps": [
                        {
                            "step": i,
                            "tool_name": s.tool_name,
                            "reason": s.reason,
                            "inputs": dict(s.inputs),
                            "depends_on": s.depends_on,
                            "result_selector": s.result_selector,
                        }
                        for i, s in enumerate(validated.plan, start=1)
                    ],
                    "rejected_steps": [],
                },
            )
        return validated


def _llm_plan() -> LlmToolPlan:
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
        ],
    )


# ---------- App + fixture wiring -------------------------------------------


def _make_app(*, planner, mcp_tools, handlers, mcp_client_bound: bool = True) -> Any:
    mcp_client = MockMcpClient(tools=mcp_tools, handlers=handlers)
    app = create_app()
    settings = get_settings()
    if mcp_client_bound:
        app.state.mcp_client = mcp_client
        app.state.mcp_status = McpDependencyStatus(
            status="mock",
            url=settings.mcp_server_url,
            transport=settings.mcp_transport,
            error=None,
        )
    else:
        app.state.mcp_client = None
        app.state.mcp_status = McpDependencyStatus(
            status="unavailable",
            url=settings.mcp_server_url,
            transport=settings.mcp_transport,
            error="seeded for test",
        )
    app.state.llm_planner = planner
    return app


@pytest_asyncio.fixture()
async def llm_stream_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(
        planner=FakeLlmPlanner(canned_plan=_llm_plan()),
        mcp_tools=[SEARCH_TOOL, DETAIL_TOOL],
        handlers={
            "searchCandidates": _search_handler,
            "getCandidateDetail": _detail_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def empty_llm_stream_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(
        planner=FakeLlmPlanner(canned_plan=_llm_plan()),
        mcp_tools=[SEARCH_TOOL, DETAIL_TOOL],
        handlers={
            "searchCandidates": _empty_search_handler,
            "getCandidateDetail": _detail_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def unavailable_stream_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(
        planner=FakeLlmPlanner(canned_plan=_llm_plan()),
        mcp_tools=[SEARCH_TOOL],
        handlers={"searchCandidates": _search_handler},
        mcp_client_bound=False,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def deterministic_stream_client() -> AsyncIterator[AsyncClient]:
    # No LLM planner — exercises deterministic graph's emission points.
    app = _make_app(
        planner=None,
        mcp_tools=[],  # default MockMcpClient catalogue overridden to empty
        handlers={},
    )
    # Default MockMcpClient catalogue includes search_consultants. Reset
    # so the deterministic path produces no candidates and we still
    # observe tools_discovered/plan_validated/results_normalized.
    app.state.mcp_client = MockMcpClient()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Helpers --------------------------------------------------------


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse a complete SSE body into a list of {type, data} dicts."""
    events: list[dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue
        event_type = None
        data_line = None
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_line = line[len("data:") :].strip()
        if event_type is None or data_line is None:
            continue
        events.append({"type": event_type, "data": json.loads(data_line)})
    return events


async def _collect(client: AsyncClient, query: str) -> tuple[str, list[dict]]:
    response = await client.post(
        "/api/search/stream",
        json={"query": query, "filters": {}},
    )
    body = response.text
    return body, _parse_sse(body)


# ---------- Tests ----------------------------------------------------------


QUERY = (
    "search a dev who has more 10 years experience on java and his last "
    "experience should be in CIB"
)


@pytest.mark.asyncio
async def test_stream_endpoint_returns_text_event_stream_content_type(
    llm_stream_client: AsyncClient,
) -> None:
    response = await llm_stream_client.post(
        "/api/search/stream",
        json={"query": QUERY, "filters": {}},
    )
    assert response.status_code == 200
    # ASGITransport delivers media_type with charset; just check prefix.
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_stream_begins_with_search_started_and_ends_with_final_response(
    llm_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(llm_stream_client, QUERY)
    assert events, "stream produced no events"
    assert events[0]["type"] == "search_started"
    assert events[-1]["type"] == "final_response"
    assert events[0]["data"]["planner_mode"] == "llm"
    assert events[0]["data"]["query"] == QUERY
    assert events[0]["data"]["conversation_id"].startswith("conv_")


@pytest.mark.asyncio
async def test_stream_llm_path_emits_full_event_sequence(
    llm_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(llm_stream_client, QUERY)
    types = [e["type"] for e in events]
    for required in (
        "search_started",
        "tools_discovered",
        "plan_created",
        "plan_validated",
        "tool_call_started",
        "tool_call_completed",
        "results_normalized",
        "candidate_cards_partial",
        "final_response",
    ):
        assert required in types, f"missing {required!r} in {types}"

    # tools_discovered carries just (name, input_schema_keys) — no raw schema.
    tools_event = next(e for e in events if e["type"] == "tools_discovered")
    for tool in tools_event["data"]["tools"]:
        assert set(tool.keys()) == {"name", "input_schema_keys"}
        assert isinstance(tool["input_schema_keys"], list)

    # final_response mirrors the non-streaming SearchResponse contract.
    final = next(e for e in events if e["type"] == "final_response")["data"]
    assert set(final.keys()) == {"conversation_id", "message", "ui"}
    assert final["ui"]["type"] == "candidate_cards"


@pytest.mark.asyncio
async def test_stream_tool_call_completed_carries_result_count(
    llm_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(llm_stream_client, QUERY)
    completions = [e for e in events if e["type"] == "tool_call_completed"]
    assert completions, "no tool_call_completed emitted"
    search_completion = next(
        e for e in completions if e["data"]["tool"] == "searchCandidates"
    )
    assert search_completion["data"]["status"] == "success"
    assert search_completion["data"]["result_count"] == len(_SEARCH_RECORDS)


@pytest.mark.asyncio
async def test_stream_empty_search_reports_zero_results_and_empty_cards(
    empty_llm_stream_client: AsyncClient,
) -> None:
    body, events = await _collect(empty_llm_stream_client, QUERY)
    completions = [
        e
        for e in events
        if e["type"] == "tool_call_completed"
        and e["data"]["tool"] == "searchCandidates"
    ]
    assert completions
    assert completions[0]["data"]["result_count"] == 0

    final = next(e for e in events if e["type"] == "final_response")["data"]
    assert final["ui"]["candidates"] == []

    # Raw MCP attributes/firstName/lastName must never appear in the stream.
    assert "firstName" not in body
    assert "lastName" not in body
    assert "attributes" not in body


@pytest.mark.asyncio
async def test_stream_mcp_unavailable_emits_search_failed(
    unavailable_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(unavailable_stream_client, QUERY)
    failures = [e for e in events if e["type"] == "search_failed"]
    assert failures, f"expected search_failed event, got {[e['type'] for e in events]}"
    payload = failures[-1]["data"]
    assert payload["error"]["code"] == "mcp_client_unavailable"
    # No final_response on the failure path.
    assert not any(e["type"] == "final_response" for e in events)


@pytest.mark.asyncio
async def test_stream_never_leaks_chain_of_thought_or_secrets(
    llm_stream_client: AsyncClient,
) -> None:
    body, _ = await _collect(llm_stream_client, QUERY)
    # Sanity-check for fields/keywords that must not appear.
    for forbidden in (
        "chain_of_thought",
        "thinking",
        "system_prompt",
        "api_key",
        "_enrichment_detail",
        "_enrichment_technical_document",
        "raw_mcp_result",
    ):
        assert forbidden not in body, f"{forbidden!r} leaked into stream"


@pytest.mark.asyncio
async def test_non_streaming_search_endpoint_still_works(
    llm_stream_client: AsyncClient,
) -> None:
    """Regression: POST /api/search must keep its existing JSON contract."""
    response = await llm_stream_client.post(
        "/api/search", json={"query": QUERY, "filters": {}}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"conversation_id", "message", "ui"}
    assert body["ui"]["type"] == "candidate_cards"


@pytest.mark.asyncio
async def test_stream_deterministic_path_emits_planner_mode_deterministic(
    deterministic_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(deterministic_stream_client, "find java consultants")
    assert events[0]["type"] == "search_started"
    assert events[0]["data"]["planner_mode"] == "deterministic"
    types = [e["type"] for e in events]
    assert "tools_discovered" in types
    assert "plan_created" in types
    assert "plan_validated" in types
    assert events[-1]["type"] == "final_response"


# ---------------------------------------------------------------------------
# Regression: dictionary-before-search plan must still run searchCandidates
# ---------------------------------------------------------------------------


DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Fetch a BoondManager dictionary.",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
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


_dictionary_plan_calls: list[tuple[str, dict]] = []


async def _dict_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
    _dictionary_plan_calls.append(("getDictionary", dict(inputs)))
    return [{"id": "exp-4", "label": "10+ years"}]


async def _search_handler_recording(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _dictionary_plan_calls.append(("searchCandidates", dict(inputs)))
    return list(_SEARCH_RECORDS)


async def _detail_handler_recording(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _dictionary_plan_calls.append(("getCandidateDetail", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    return [
        {
            "id": str(cid),
            "type": "candidate",
            "attributes": {"firstName": "Sarah", "lastName": "Martin"},
        }
    ]


async def _tech_doc_handler_recording(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _dictionary_plan_calls.append(
        ("getCandidateTechnicalDocument", dict(inputs))
    )
    return [{"candidateId": int(inputs.get("candidateId") or 0), "skills": ["Java"]}]


@dataclass
class CannedRawPlanPlanner:
    """Planner that ignores validate_plan and emits its raw plan as-is.

    The shape we want to test (depends_on with result_selector=null on
    `searchCandidates`) is exactly what the validator should now allow;
    using ``validate_plan`` here also exercises the new validation path.
    """

    canned_plan: LlmToolPlan

    async def plan(
        self,
        *,
        query: str,
        filters: dict[str, object],
        tools,
        constraints: PlannerConstraints,
        emitter=None,
    ):
        return validate_plan(self.canned_plan, list(tools), constraints)


def _dictionary_before_search_plan() -> LlmToolPlan:
    """The exact plan shape that triggered the bug in production."""
    return LlmToolPlan(
        interpreted_intent={"objective": "candidate_search"},
        plan=[
            PlannedToolCall(
                tool_name="getDictionary",
                inputs={"key": "experience"},
                reason="resolve experience dictionary",
            ),
            PlannedToolCall(
                tool_name="searchCandidates",
                inputs={
                    "keywords": "+java CIB",
                    "page": 1,
                    "numberPerPage": 10,
                },
                depends_on="getDictionary",
                result_selector=None,
                reason="run search after dictionary is fetched",
            ),
            PlannedToolCall(
                tool_name="getCandidateDetail",
                inputs={},
                depends_on="searchCandidates",
                result_selector="candidate_ids",
                reason="enrich shortlisted candidates",
            ),
            PlannedToolCall(
                tool_name="getCandidateTechnicalDocument",
                inputs={},
                depends_on="searchCandidates",
                result_selector="candidate_ids",
                reason="verify technical fit",
            ),
        ],
    )


@pytest_asyncio.fixture()
async def dictionary_before_search_client() -> AsyncIterator[AsyncClient]:
    _dictionary_plan_calls.clear()
    app = _make_app(
        planner=CannedRawPlanPlanner(canned_plan=_dictionary_before_search_plan()),
        mcp_tools=[
            DICTIONARY_TOOL,
            SEARCH_TOOL,
            DETAIL_TOOL,
            TECH_DOC_TOOL,
        ],
        handlers={
            "getDictionary": _dict_handler,
            "searchCandidates": _search_handler_recording,
            "getCandidateDetail": _detail_handler_recording,
            "getCandidateTechnicalDocument": _tech_doc_handler_recording,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_dictionary_before_search_still_runs_search_candidates(
    dictionary_before_search_client: AsyncClient,
) -> None:
    """Regression: depends_on without candidate_ids selector must NOT be
    treated as fan-out. The original bug skipped ``searchCandidates``
    because it had ``depends_on='getDictionary'`` and the executor
    tried (and failed) to extract candidate ids from dictionary output.
    """
    _, events = await _collect(dictionary_before_search_client, QUERY)
    tool_names = [name for name, _ in _dictionary_plan_calls]

    # getDictionary must run before searchCandidates (plan order).
    assert tool_names.count("getDictionary") == 1
    assert tool_names.count("searchCandidates") == 1
    assert tool_names.index("getDictionary") < tool_names.index("searchCandidates")

    # searchCandidates inputs must be the LLM-supplied schema-valid
    # values, NOT a per-id fan-out call.
    search_call = next(
        args for name, args in _dictionary_plan_calls if name == "searchCandidates"
    )
    assert search_call.get("keywords") == "+java CIB"
    assert search_call.get("page") == 1


@pytest.mark.asyncio
async def test_dictionary_before_search_fans_out_detail_from_candidates_only(
    dictionary_before_search_client: AsyncClient,
) -> None:
    await _collect(dictionary_before_search_client, QUERY)
    detail_calls = [
        args
        for name, args in _dictionary_plan_calls
        if name == "getCandidateDetail"
    ]
    # Fan-out must use ids from searchCandidates, not dictionary entries.
    assert detail_calls, "expected at least one getCandidateDetail call"
    detail_ids = {
        int(args.get("candidateId") or args.get("id") or 0) for args in detail_calls
    }
    assert detail_ids == {41924}  # the id from _SEARCH_RECORDS


@pytest.mark.asyncio
async def test_dictionary_output_does_not_appear_as_candidate(
    dictionary_before_search_client: AsyncClient,
) -> None:
    _, events = await _collect(dictionary_before_search_client, QUERY)
    final = next(e for e in events if e["type"] == "final_response")["data"]
    candidate_ids = [c["id"] for c in final["ui"]["candidates"]]
    # The dictionary id ("exp-4") must NEVER appear in the candidate list.
    assert "exp-4" not in candidate_ids
    # We should only see the searchCandidates-produced candidate.
    assert candidate_ids == ["41924"]

    # results_normalized must report only the search candidate id,
    # not the dictionary record.
    normalized = next(e for e in events if e["type"] == "results_normalized")["data"]
    assert "exp-4" not in normalized["candidate_ids"]
    assert "41924" in normalized["candidate_ids"]


@pytest.mark.asyncio
async def test_message_does_not_falsely_claim_no_candidates_when_search_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the LLM-planned candidate search never runs (e.g. a tool
    failure or, in a future regression, the bug we just fixed), the
    final_response must not pretend a real search returned zero results.
    """

    async def _empty_search(_: dict[str, object]) -> list[dict[str, object]]:
        return []

    _dictionary_plan_calls.clear()
    app = _make_app(
        planner=CannedRawPlanPlanner(
            canned_plan=LlmToolPlan(
                plan=[
                    PlannedToolCall(
                        tool_name="getDictionary",
                        inputs={"key": "experience"},
                    )
                ]
            )
        ),
        mcp_tools=[DICTIONARY_TOOL],
        handlers={"getDictionary": _dict_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        _, events = await _collect(ac, QUERY)

    final = next(e for e in events if e["type"] == "final_response")["data"]
    # No candidate-producing search tool was invoked; message must NOT
    # claim "No candidates matched your search."
    assert "No candidates matched your search" not in final["message"]
    assert final["ui"]["candidates"] == []


@pytest.mark.asyncio
async def test_message_says_no_candidates_only_when_search_actually_ran(
    empty_llm_stream_client: AsyncClient,
) -> None:
    """When ``searchCandidates`` actually ran and returned [], the
    'No candidates matched your search.' phrasing IS the correct one.
    """
    _, events = await _collect(empty_llm_stream_client, QUERY)
    final = next(e for e in events if e["type"] == "final_response")["data"]
    assert "No candidates matched your search" in final["message"]


# ---------------------------------------------------------------------------
# Regression: searchCandidates returns records the mapper cannot normalize
# ---------------------------------------------------------------------------


_UNMAPPABLE_SEARCH_RECORDS = [
    # Record has no `id`, no `attributes.id`, no candidateId — exactly
    # the failure mode the production bug exhibited.
    {
        "type": "candidate",
        "attributes": {
            "firstName": "Sarah",
            "lastName": "Martin",
            "city": "Paris",
        },
    }
]


async def _unmappable_search_handler(
    _: dict[str, object],
) -> list[dict[str, object]]:
    return list(_UNMAPPABLE_SEARCH_RECORDS)


def _direct_search_plan() -> LlmToolPlan:
    return LlmToolPlan(
        plan=[
            PlannedToolCall(
                tool_name="searchCandidates",
                inputs={"keywords": "java", "page": 1, "numberPerPage": 10},
            )
        ],
    )


@pytest_asyncio.fixture()
async def unmappable_search_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(
        planner=FakeLlmPlanner(canned_plan=_direct_search_plan()),
        mcp_tools=[SEARCH_TOOL],
        handlers={"searchCandidates": _unmappable_search_handler},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_unmappable_records_produce_drop_reasons_in_results_normalized(
    unmappable_search_client: AsyncClient,
) -> None:
    _, events = await _collect(unmappable_search_client, QUERY)
    normalized = next(e for e in events if e["type"] == "results_normalized")["data"]
    assert normalized["candidate_count"] == 1
    assert normalized["candidate_card_count"] == 0
    assert normalized["dropped_count"] == 1
    drops = normalized["drop_reasons"]
    assert drops, "expected drop_reasons to be populated"
    assert drops[0]["source_tool"] == "searchCandidates"
    assert "no resolvable" in drops[0]["reason"]
    # Safe to surface: only the keys, never the values.
    assert "Sarah" not in repr(drops)


@pytest.mark.asyncio
async def test_final_message_says_records_returned_but_not_normalized(
    unmappable_search_client: AsyncClient,
) -> None:
    _, events = await _collect(unmappable_search_client, QUERY)
    final = next(e for e in events if e["type"] == "final_response")["data"]
    assert "No candidates matched your search" not in final["message"]
    assert "could not be normalized" in final["message"]
    assert final["ui"]["candidates"] == []


@pytest.mark.asyncio
async def test_tool_call_completed_includes_result_shape_summary(
    llm_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(llm_stream_client, QUERY)
    completed = [
        e
        for e in events
        if e["type"] == "tool_call_completed"
        and e["data"]["tool"] == "searchCandidates"
    ]
    assert completed
    shape = completed[0]["data"]["result_shape"]
    assert shape["record_count"] >= 1
    # Top-level keys must be present (we expect at least "id" or
    # "attributes" depending on the fixture).
    assert isinstance(shape["top_level_keys"], list)


@pytest.mark.asyncio
async def test_normal_stream_does_not_include_result_preview(
    llm_stream_client: AsyncClient,
) -> None:
    _, events = await _collect(llm_stream_client, QUERY)
    completed = [e for e in events if e["type"] == "tool_call_completed"]
    for event in completed:
        assert "result_preview" not in event["data"], (
            "result_preview must not appear without debug mode"
        )
    # Defence in depth: raw MCP record VALUES must not appear in the
    # observability events. The final_response event legitimately
    # contains candidate values (full_name, location, etc.) — those are
    # the public contract — so we scope this check to the observability
    # surface only.
    observability_text = repr(
        [
            e
            for e in events
            if e["type"]
            in {"tool_call_started", "tool_call_completed", "results_normalized"}
        ]
    )
    # Key names like "firstName" appear inside result_shape.nested_keys
    # by design — they are schema-level structural metadata, not values.
    for value in ("Sarah", "Martin", "Paris", "France"):
        assert value not in observability_text, (
            f"raw MCP value {value!r} must not surface in observability events"
        )


# ---------------------------------------------------------------------------
# Regression: searchCandidates returns `{"candidates": [...], "meta": {...}}`
# ---------------------------------------------------------------------------


_REAL_SHAPE_SEARCH_PAYLOAD = {
    "candidates": [
        {
            "id": "41924",
            "firstName": "Sarah",
            "lastName": "Martin",
            "city": "Paris",
            "country": "France",
            "availabilityDate": "2026-07-01",
            "availabilityType": "available",
            "contractType": "salaried",
            "email": "sarah@example.com",
            "maxSalary": 120000,
            "maxTjm": 900,
            "minSalary": 90000,
            "minTjm": 700,
            "mobilityArea": "EU",
            "state": "active",
            "technicalDocument": "doc-1",
        },
        {
            "id": "41925",
            "firstName": "Alex",
            "lastName": "Dupont",
            "city": "Lyon",
            "country": "France",
            "availabilityDate": "2026-08-01",
            "availabilityType": "available",
            "contractType": "freelance",
            "email": "alex@example.com",
            "maxSalary": None,
            "maxTjm": 950,
            "minSalary": None,
            "minTjm": 750,
            "mobilityArea": "EU",
            "state": "active",
            "technicalDocument": "doc-2",
        },
    ],
    "meta": {"currentPage": 1, "totalRows": 2},
}


_wrapper_calls: list[tuple[str, dict]] = []


async def _real_shape_search_handler(
    inputs: dict[str, object],
) -> dict[str, object]:
    """Returns the production envelope: NOT a list — a wrapper dict."""
    _wrapper_calls.append(("searchCandidates", dict(inputs)))
    return _REAL_SHAPE_SEARCH_PAYLOAD


async def _wrapper_detail_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    _wrapper_calls.append(("getCandidateDetail", dict(inputs)))
    cid = int(inputs.get("candidateId") or inputs.get("id") or 0)
    return [
        {
            "id": str(cid),
            "type": "candidate",
            "attributes": {"firstName": "Sarah", "experienceYears": 12},
        }
    ]


def _real_shape_search_plan() -> LlmToolPlan:
    return LlmToolPlan(
        plan=[
            PlannedToolCall(
                tool_name="searchCandidates",
                inputs={"keywords": "java", "page": 1, "numberPerPage": 10},
            ),
            PlannedToolCall(
                tool_name="getCandidateDetail",
                inputs={},
                depends_on="searchCandidates",
                result_selector="candidate_ids",
            ),
        ]
    )


@pytest_asyncio.fixture()
async def real_shape_search_client() -> AsyncIterator[AsyncClient]:
    _wrapper_calls.clear()
    app = _make_app(
        planner=FakeLlmPlanner(canned_plan=_real_shape_search_plan()),
        mcp_tools=[SEARCH_TOOL, DETAIL_TOOL],
        handlers={
            "searchCandidates": _real_shape_search_handler,
            "getCandidateDetail": _wrapper_detail_handler,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_wrapper_envelope_unwraps_into_search_results(
    real_shape_search_client: AsyncClient,
) -> None:
    _, events = await _collect(real_shape_search_client, QUERY)
    normalized = next(e for e in events if e["type"] == "results_normalized")["data"]
    # Both unwrapped candidates must appear as SearchResults AND as cards.
    assert normalized["candidate_ids"] == ["41924", "41925"]
    assert normalized["candidate_card_count"] == 2
    assert normalized["dropped_count"] == 0


@pytest.mark.asyncio
async def test_wrapper_envelope_meta_is_not_treated_as_candidate(
    real_shape_search_client: AsyncClient,
) -> None:
    _, events = await _collect(real_shape_search_client, QUERY)
    normalized = next(e for e in events if e["type"] == "results_normalized")["data"]
    # No id collision with "meta", no extra candidate spawned from the
    # pagination block.
    assert "meta" not in normalized["candidate_ids"]
    assert "currentPage" not in normalized["candidate_ids"]
    assert normalized["candidate_card_count"] == 2


@pytest.mark.asyncio
async def test_wrapper_envelope_emits_candidate_cards_partial(
    real_shape_search_client: AsyncClient,
) -> None:
    _, events = await _collect(real_shape_search_client, QUERY)
    partials = [e for e in events if e["type"] == "candidate_cards_partial"]
    assert partials
    last_partial = partials[-1]["data"]
    ids = [c["id"] for c in last_partial["candidates"]]
    assert ids == ["41924", "41925"] or ids == ["41925", "41924"]


@pytest.mark.asyncio
async def test_wrapper_envelope_fans_out_detail_over_unwrapped_ids(
    real_shape_search_client: AsyncClient,
) -> None:
    await _collect(real_shape_search_client, QUERY)
    detail_ids = {
        int(args.get("candidateId") or args.get("id") or 0)
        for name, args in _wrapper_calls
        if name == "getCandidateDetail"
    }
    assert detail_ids == {41924, 41925}


@pytest.mark.asyncio
async def test_wrapper_envelope_final_response_contains_cards_not_failure_message(
    real_shape_search_client: AsyncClient,
) -> None:
    _, events = await _collect(real_shape_search_client, QUERY)
    final = next(e for e in events if e["type"] == "final_response")["data"]
    candidate_ids = [c["id"] for c in final["ui"]["candidates"]]
    assert set(candidate_ids) == {"41924", "41925"}
    # The old misleading message must NOT appear.
    assert "could not be normalized" not in final["message"]
    assert "No candidates matched" not in final["message"]


@pytest.mark.asyncio
async def test_debug_stream_includes_sanitized_result_preview(
    llm_stream_client: AsyncClient,
) -> None:
    response = await llm_stream_client.post(
        "/api/search/stream",
        headers={"X-Agent-Debug": "true"},
        json={"query": QUERY, "filters": {}},
    )
    events = _parse_sse(response.text)
    completed = [
        e
        for e in events
        if e["type"] == "tool_call_completed"
        and e["data"]["tool"] == "searchCandidates"
    ]
    assert completed
    preview = completed[0]["data"].get("result_preview")
    assert isinstance(preview, list)
    assert preview, "expected a sanitized preview in debug mode"
    # Preview must be capped to a small number of records.
    assert len(preview) <= 2
