"""Deterministic source routing + failure isolation through SearchService.

Uses a spy MCP client (records every candidate-search tool call) and a fake
external source (records discover calls), both injected. No LLM, no network.
"""

from __future__ import annotations

import pytest

from app.candidate_sources.linkedin_web.source import (
    ExternalDiscoveryResult,
    ScoredExternalCandidate,
)
from app.candidate_sources.models import (
    ConsultingProfileEvidence,
    ExternalCandidateEvidence,
    LongMissionEvidence,
)
from app.mcp.client import McpToolError
from app.mcp.mock_client import MockMcpClient
from app.models.api import SearchRequest
from app.services.search_service import SearchService

_BOOND_SEARCH_TOOLS = {"search_consultants", "searchCandidates", "getCandidateDetail"}


class SpyMcpClient(MockMcpClient):
    """MockMcpClient that records every call_tool invocation."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.calls: list[str] = []

    async def call_tool(self, tool: str, inputs: dict[str, object]):
        self.calls.append(tool)
        return await super().call_tool(tool, inputs)

    def boond_search_calls(self) -> list[str]:
        return [c for c in self.calls if c in _BOOND_SEARCH_TOOLS]


class FakeExternalSource:
    """Records discover() calls; returns scripted candidates or raises."""

    def __init__(self, *, candidates: int = 2, raises: bool = False) -> None:
        self._n = candidates
        self._raises = raises
        self.discover_calls = 0

    async def discover(self, query) -> ExternalDiscoveryResult:
        self.discover_calls += 1
        if self._raises:
            raise RuntimeError("external boom")
        scored = [
            ScoredExternalCandidate(
                evidence=ExternalCandidateEvidence(
                    profile_url=f"https://www.linkedin.com/in/ext-{i}",
                    full_name=f"External {i}",
                    current_title="Java Consultant",
                    matched_skills=["Java"],
                    consulting_profile=ConsultingProfileEvidence(status="confirmed"),
                    long_mission=LongMissionEvidence(status="confirmed", max_duration_months=30),
                ),
                score=0.9 - i * 0.01,
            )
            for i in range(self._n)
        ]
        return ExternalDiscoveryResult(
            candidates=scored,
            metrics={"query_count": 1, "result_count": len(scored)},
        )


def _service(mcp, external, *, enabled: bool = True) -> SearchService:
    return SearchService(
        mcp_client=mcp,
        external_source=external,
        external_search_enabled=enabled,
    )


def _linkedin_cards(resp):
    return [c for c in resp.ui.candidates if "linkedin_web" in c.sources]


def _boond_cards(resp):
    return [c for c in resp.ui.candidates if "boond" in c.sources]


@pytest.mark.asyncio
async def test_boond_only_never_calls_linkedin() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource()
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java developer", sources=["boond"])
    )
    assert external.discover_calls == 0  # LinkedIn source never runs
    assert mcp.boond_search_calls()  # Boond ran
    assert _linkedin_cards(resp) == []


@pytest.mark.asyncio
async def test_linkedin_only_never_calls_boond() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource()
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant Nantes", sources=["linkedin"])
    )
    assert mcp.boond_search_calls() == []  # Boond search never runs
    assert external.discover_calls == 1
    assert _boond_cards(resp) == []
    assert len(_linkedin_cards(resp)) >= 1


@pytest.mark.asyncio
async def test_both_runs_both_sources() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource()
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant", sources=["boond", "linkedin"])
    )
    assert mcp.boond_search_calls()
    assert external.discover_calls == 1
    assert _boond_cards(resp) and _linkedin_cards(resp)


@pytest.mark.asyncio
async def test_no_source_selected_runs_both_when_enabled() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource()
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant")  # sources omitted
    )
    assert mcp.boond_search_calls()
    assert external.discover_calls == 1


@pytest.mark.asyncio
async def test_no_source_selected_boond_only_when_external_disabled() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource()
    resp = await _service(mcp, external, enabled=False).search(
        SearchRequest(query="Java consultant")
    )
    assert mcp.boond_search_calls()
    assert external.discover_calls == 0
    assert _linkedin_cards(resp) == []


# --- 43: partial source failure ---------------------------------------------
@pytest.mark.asyncio
async def test_both_boond_ok_linkedin_fails_returns_boond() -> None:
    mcp = SpyMcpClient()
    external = FakeExternalSource(raises=True)
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant", sources=["boond", "linkedin"])
    )
    assert _boond_cards(resp)  # Boond results survive the LinkedIn failure
    assert _linkedin_cards(resp) == []


@pytest.mark.asyncio
async def test_both_linkedin_ok_boond_fails_returns_linkedin() -> None:
    mcp = SpyMcpClient(failures={"search_consultants": McpToolError("down", tool="search_consultants")})
    external = FakeExternalSource()
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant", sources=["boond", "linkedin"])
    )
    assert len(_linkedin_cards(resp)) >= 1  # LinkedIn results survive Boond failure


# --- 35: the LLM planner must NOT be able to override source selection ------
class _PlanningLlm:
    """Fake planner that always wants to run a Boond searchCandidates step."""

    async def plan(self, *, query, filters, tools, constraints, emitter=None, **_):
        from app.models.intent import LlmToolPlan, PlannedToolCall

        return LlmToolPlan(
            interpreted_intent={"objective": "candidate_search",
                                "entities": ["java"], "constraints": {}},
            plan=[PlannedToolCall(tool_name="searchCandidates",
                                  inputs={"keywords": "java", "page": 1})],
        )


@pytest.mark.asyncio
async def test_llm_planner_cannot_override_linkedin_only() -> None:
    from app.models.tools import McpTool

    tools = [
        McpTool(name="searchCandidates", description="search",
                input_schema={"type": "object", "properties": {
                    "keywords": {"type": "string"}, "page": {"type": "integer"}}}),
    ]
    mcp = SpyMcpClient(tools=tools)
    external = FakeExternalSource()
    service = SearchService(
        mcp_client=mcp,
        llm_planner=_PlanningLlm(),
        external_source=external,
        external_search_enabled=True,
    )
    resp = await service.search(
        SearchRequest(query="Java consultant", sources=["linkedin"])
    )
    # The LLM planned a Boond search, but LinkedIn-only routing wins.
    assert mcp.boond_search_calls() == []
    assert external.discover_calls == 1
    assert len(_linkedin_cards(resp)) >= 1


# --- external discovery defaults geography to France when none given --------
def test_external_query_defaults_location_when_none() -> None:
    from app.graph.nodes import NodeContext, _candidate_search_query_from_state
    from app.models.graph_state import GraphState
    from app.models.intent import InterpretedIntent

    ctx = NodeContext(mcp_client=MockMcpClient(),
                      external_default_location="Île-de-France, France")
    state = GraphState(
        original_query="développeur java",
        sources=["linkedin"],
        interpreted_intent=InterpretedIntent(objective="x", entities=["java"], constraints={}),
    )
    q = _candidate_search_query_from_state(state, ctx)
    assert q.location == "Île-de-France, France"


def test_external_query_uses_stated_location_over_default() -> None:
    from app.graph.nodes import NodeContext, _candidate_search_query_from_state
    from app.models.graph_state import GraphState
    from app.models.intent import InterpretedIntent

    ctx = NodeContext(mcp_client=MockMcpClient(),
                      external_default_location="Île-de-France, France")
    state = GraphState(
        original_query="dev java à Nantes",
        sources=["linkedin"],
        interpreted_intent=InterpretedIntent(
            objective="x", entities=["java"], constraints={"location": "Nantes"}),
    )
    q = _candidate_search_query_from_state(state, ctx)
    assert q.location == "Nantes"


@pytest.mark.asyncio
async def test_linkedin_only_message_has_no_boond_verify_wording() -> None:
    # The Boond-style "could not verify criteria" wording must not appear for a
    # LinkedIn-only search (public profiles have no technical doc to verify).
    mcp = SpyMcpClient()
    external = FakeExternalSource(candidates=2)
    resp = await _service(mcp, external).search(
        SearchRequest(query="Java consultant Paris", sources=["linkedin"])
    )
    assert len(_linkedin_cards(resp)) == 2
    lowered = resp.message.lower()
    assert "verify" not in lowered and "vérifier" not in lowered
