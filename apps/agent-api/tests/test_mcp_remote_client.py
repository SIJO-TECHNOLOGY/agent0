"""Tests for RemoteMcpClient.

The tests inject a fake `ClientSession` directly into the client so
the SDK's transport layer is not exercised. Transport-level failures
are covered separately by patching `streamablehttp_client` to raise.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import (
    CallToolResult,
    ErrorData,
    ListToolsResult,
    TextContent,
    Tool,
)

import app.mcp.remote_client as remote_module
from app.mcp.client import McpToolError, McpTransientError
from app.mcp.remote_client import RemoteMcpClient


class _FakeSession:
    """Stand-in for `mcp.ClientSession` used inside RemoteMcpClient."""

    def __init__(
        self,
        *,
        tools: list[Tool] | None = None,
        call_tool_result: CallToolResult | None = None,
        list_tools_exc: BaseException | None = None,
        call_tool_exc: BaseException | None = None,
    ) -> None:
        self._tools = tools or []
        self._call_tool_result = call_tool_result
        self._list_tools_exc = list_tools_exc
        self._call_tool_exc = call_tool_exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self):
        if self._list_tools_exc is not None:
            raise self._list_tools_exc
        return ListToolsResult(tools=self._tools)

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None):
        self.calls.append((name, dict(arguments or {})))
        if self._call_tool_exc is not None:
            raise self._call_tool_exc
        assert self._call_tool_result is not None
        return self._call_tool_result


def _client_with_session(session: _FakeSession) -> RemoteMcpClient:
    client = RemoteMcpClient(url="http://fake.test/mcp", timeout_seconds=1.0)
    client._session = session  # type: ignore[attr-defined]
    return client


def _text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


@pytest.mark.asyncio
async def test_discover_tools_maps_metadata() -> None:
    tools = [
        Tool(
            name="search_consultants",
            description="Find consultants.",
            inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
        ),
        Tool(name="search_projects", description=None, inputSchema={}),
    ]
    client = _client_with_session(_FakeSession(tools=tools))

    result = await client.discover_tools()

    assert [t.name for t in result] == ["search_consultants", "search_projects"]
    assert result[0].description == "Find consultants."
    assert result[0].input_schema == {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    assert result[1].description == ""  # None coerced to empty string


@pytest.mark.asyncio
async def test_call_tool_maps_structured_dict_to_single_record() -> None:
    structured = {"id": "c-1", "type": "consultant", "score": 0.9}
    result = CallToolResult(content=[], structuredContent=structured, isError=False)
    client = _client_with_session(_FakeSession(call_tool_result=result))

    records = await client.call_tool("search_consultants", {"q": "py"})

    assert records == [structured]


@pytest.mark.asyncio
async def test_call_tool_unwraps_results_key_from_structured_dict() -> None:
    structured = {"results": [{"id": "a"}, {"id": "b"}]}
    result = CallToolResult(content=[], structuredContent=structured, isError=False)
    client = _client_with_session(_FakeSession(call_tool_result=result))

    records = await client.call_tool("search_consultants", {})

    assert records == [{"id": "a"}, {"id": "b"}]


@pytest.mark.asyncio
async def test_call_tool_unwraps_candidates_key_from_structured_dict() -> None:
    structured = {"candidates": [{"id": "c1"}, {"id": "c2"}]}
    result = CallToolResult(content=[], structuredContent=structured, isError=False)
    client = _client_with_session(_FakeSession(call_tool_result=result))

    records = await client.call_tool("searchCandidates", {})

    assert records == [{"id": "c1"}, {"id": "c2"}]


@pytest.mark.asyncio
async def test_call_tool_parses_json_text_array() -> None:
    result = _text_result('[{"id":"x"},{"id":"y"}]')
    client = _client_with_session(_FakeSession(call_tool_result=result))

    records = await client.call_tool("search_consultants", {})

    assert records == [{"id": "x"}, {"id": "y"}]


@pytest.mark.asyncio
async def test_call_tool_parses_json_text_object_into_single_record() -> None:
    result = _text_result('{"id":"z"}')
    client = _client_with_session(_FakeSession(call_tool_result=result))

    records = await client.call_tool("search_consultants", {})

    assert records == [{"id": "z"}]


@pytest.mark.asyncio
async def test_call_tool_raises_on_non_json_text() -> None:
    result = _text_result("plain narrative text, not JSON")
    client = _client_with_session(_FakeSession(call_tool_result=result))

    with pytest.raises(McpToolError) as excinfo:
        await client.call_tool("search_consultants", {})

    assert "non-JSON" in str(excinfo.value)


@pytest.mark.asyncio
async def test_call_tool_raises_when_is_error_true() -> None:
    result = _text_result("invalid argument: q", is_error=True)
    client = _client_with_session(_FakeSession(call_tool_result=result))

    with pytest.raises(McpToolError) as excinfo:
        await client.call_tool("search_consultants", {})

    assert "invalid argument" in str(excinfo.value)


@pytest.mark.asyncio
async def test_call_tool_maps_mcp_error_to_tool_error() -> None:
    err = McpError(error=ErrorData(code=-32602, message="Invalid params"))
    client = _client_with_session(_FakeSession(call_tool_exc=err))

    with pytest.raises(McpToolError):
        await client.call_tool("search_consultants", {})


@pytest.mark.asyncio
async def test_call_tool_maps_transport_error_to_transient() -> None:
    boom = httpx.ConnectError("connection refused")
    client = _client_with_session(_FakeSession(call_tool_exc=boom))

    with pytest.raises(McpTransientError):
        await client.call_tool("search_consultants", {})


@pytest.mark.asyncio
async def test_discover_tools_maps_transport_error_to_transient() -> None:
    boom = httpx.ReadTimeout("read timed out")
    client = _client_with_session(_FakeSession(list_tools_exc=boom))

    with pytest.raises(McpTransientError):
        await client.discover_tools()


@pytest.mark.asyncio
async def test_connect_wraps_transport_failure_as_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def boom_streamable(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("server down")
        yield  # pragma: no cover

    monkeypatch.setattr(remote_module, "streamablehttp_client", boom_streamable)

    client = RemoteMcpClient(url="http://fake.test/mcp", timeout_seconds=1.0)
    with pytest.raises(McpTransientError):
        await client.connect()


@pytest.mark.asyncio
async def test_aclose_is_idempotent_when_not_connected() -> None:
    client = RemoteMcpClient(url="http://fake.test/mcp")
    await client.aclose()  # must not raise
    await client.aclose()


@pytest.mark.asyncio
async def test_connect_wraps_cancelled_error_as_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MCP SDK's TaskGroup can raise CancelledError during init when
    the server is down. RemoteMcpClient must convert this to McpTransientError
    so graceful degradation can mark MCP unavailable."""

    @asynccontextmanager
    async def cancelled_streamable(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise asyncio.CancelledError("simulated SDK cancel")
        yield  # pragma: no cover

    monkeypatch.setattr(remote_module, "streamablehttp_client", cancelled_streamable)

    client = RemoteMcpClient(url="http://fake.test/mcp", timeout_seconds=1.0)
    with pytest.raises(McpTransientError) as excinfo:
        await client.connect()

    message = str(excinfo.value)
    assert "http://fake.test/mcp" in message
    assert "cancel" in message.lower()
