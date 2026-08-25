"""Tests for the TTL-caching MCP client decorator (ADR-013)."""

from __future__ import annotations

import pytest

from app.mcp.caching_client import (
    DICTIONARY_TOOL,
    RESUME_TOOL,
    TECHNICAL_DOCUMENT_TOOL,
    CachingMcpClient,
)
from app.models.tools import McpTool


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingClient:
    """Inner client stub that counts calls and serves canned responses."""

    def __init__(self) -> None:
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.discover_calls = 0
        self.responses: dict[str, list[dict[str, object]]] = {}
        self.tools: list[McpTool] = [
            McpTool(name="searchCandidates", description="", input_schema={})
        ]

    async def discover_tools(self) -> list[McpTool]:
        self.discover_calls += 1
        return list(self.tools)

    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        self.tool_calls.append((tool, dict(inputs)))
        return self.responses.get(tool, [])


def _make(
    inner: RecordingClient, clock: FakeClock, **kwargs: object
) -> CachingMcpClient:
    return CachingMcpClient(inner, clock=clock, **kwargs)  # type: ignore[arg-type]


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def inner() -> RecordingClient:
    client = RecordingClient()
    client.responses[DICTIONARY_TOOL] = [{"data": {"setting": {}}}]
    client.responses[TECHNICAL_DOCUMENT_TOOL] = [{"skills": ["java"]}]
    client.responses[RESUME_TOOL] = [{"hasContent": True, "text": "cv text"}]
    client.responses["searchCandidates"] = [{"id": "1"}]
    return client


@pytest.mark.asyncio
async def test_dictionary_is_cached_within_ttl(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock)

    first = await client.call_tool(DICTIONARY_TOOL, {})
    second = await client.call_tool(DICTIONARY_TOOL, {})

    assert first == second == [{"data": {"setting": {}}}]
    assert len(inner.tool_calls) == 1
    assert client.stats["hits"] == 1


@pytest.mark.asyncio
async def test_dictionary_refetched_after_ttl_expiry(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock, dictionary_ttl_seconds=100.0)

    await client.call_tool(DICTIONARY_TOOL, {})
    clock.advance(101.0)
    await client.call_tool(DICTIONARY_TOOL, {})

    assert len(inner.tool_calls) == 2


@pytest.mark.asyncio
async def test_candidate_docs_cached_per_candidate(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock)

    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "1"})
    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "1"})
    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "2"})

    calls = [c for c in inner.tool_calls if c[0] == TECHNICAL_DOCUMENT_TOOL]
    assert len(calls) == 2  # one per distinct candidate


@pytest.mark.asyncio
async def test_volatile_tools_are_never_cached(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock)

    await client.call_tool("searchCandidates", {"keywords": "java"})
    await client.call_tool("searchCandidates", {"keywords": "java"})

    assert len(inner.tool_calls) == 2


@pytest.mark.asyncio
async def test_empty_results_are_not_cached(
    inner: RecordingClient, clock: FakeClock
) -> None:
    inner.responses[DICTIONARY_TOOL] = []
    client = _make(inner, clock)

    await client.call_tool(DICTIONARY_TOOL, {})
    await client.call_tool(DICTIONARY_TOOL, {})

    assert len(inner.tool_calls) == 2


@pytest.mark.asyncio
async def test_cv_without_content_is_not_cached(
    inner: RecordingClient, clock: FakeClock
) -> None:
    inner.responses[RESUME_TOOL] = [{"hasContent": False}]
    client = _make(inner, clock)

    await client.call_tool(RESUME_TOOL, {"candidateId": "1"})
    await client.call_tool(RESUME_TOOL, {"candidateId": "1"})

    assert len(inner.tool_calls) == 2


@pytest.mark.asyncio
async def test_cached_result_is_isolated_from_caller_mutation(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock)

    first = await client.call_tool(RESUME_TOOL, {"candidateId": "1"})
    first[0]["text"] = "mutated"
    second = await client.call_tool(RESUME_TOOL, {"candidateId": "1"})

    assert second[0]["text"] == "cv text"


@pytest.mark.asyncio
async def test_discover_tools_cached_with_ttl(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock, tools_ttl_seconds=300.0)

    await client.discover_tools()
    await client.discover_tools()
    assert inner.discover_calls == 1

    clock.advance(301.0)
    await client.discover_tools()
    assert inner.discover_calls == 2


@pytest.mark.asyncio
async def test_zero_ttl_disables_category(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(
        inner, clock, dictionary_ttl_seconds=0.0, tools_ttl_seconds=0.0
    )

    await client.call_tool(DICTIONARY_TOOL, {})
    await client.call_tool(DICTIONARY_TOOL, {})
    await client.discover_tools()
    await client.discover_tools()

    assert len(inner.tool_calls) == 2
    assert inner.discover_calls == 2


@pytest.mark.asyncio
async def test_lru_eviction_beyond_max_entries(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock, max_entries=2)

    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "1"})
    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "2"})
    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "3"})
    # candidate 1 was least recently used -> evicted -> refetches.
    await client.call_tool(TECHNICAL_DOCUMENT_TOOL, {"candidateId": "1"})

    calls = [c for c in inner.tool_calls if c[0] == TECHNICAL_DOCUMENT_TOOL]
    assert len(calls) == 4
    assert client.stats["evictions"] == 2


@pytest.mark.asyncio
async def test_errors_propagate_and_are_not_cached(clock: FakeClock) -> None:
    class FailingClient(RecordingClient):
        async def call_tool(
            self, tool: str, inputs: dict[str, object]
        ) -> list[dict[str, object]]:
            self.tool_calls.append((tool, dict(inputs)))
            raise RuntimeError("boom")

    failing = FailingClient()
    client = _make(failing, clock)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await client.call_tool(DICTIONARY_TOOL, {})

    assert len(failing.tool_calls) == 2


@pytest.mark.asyncio
async def test_lifecycle_passthrough_and_clear(
    inner: RecordingClient, clock: FakeClock
) -> None:
    closed: list[str] = []

    class Closable(RecordingClient):
        async def connect(self) -> None:
            closed.append("connect")

        async def aclose(self) -> None:
            closed.append("aclose")

    closable = Closable()
    closable.responses[DICTIONARY_TOOL] = [{"data": {}}]
    client = _make(closable, clock)

    await client.connect()
    await client.call_tool(DICTIONARY_TOOL, {})
    await client.aclose()
    # Cache was cleared on close -> next call goes to the inner client.
    await client.call_tool(DICTIONARY_TOOL, {})

    assert closed == ["connect", "aclose"]
    assert len(closable.tool_calls) == 2


@pytest.mark.asyncio
async def test_connect_and_aclose_are_noop_without_inner_support(
    inner: RecordingClient, clock: FakeClock
) -> None:
    client = _make(inner, clock)

    await client.connect()
    await client.aclose()
