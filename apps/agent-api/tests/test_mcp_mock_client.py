"""Mock MCP client behavior tests."""

from __future__ import annotations

import pytest

from app.mcp.client import McpToolError, McpTransientError
from app.mcp.mock_client import MockMcpClient


@pytest.mark.asyncio
async def test_discover_tools_returns_default_catalogue() -> None:
    client = MockMcpClient()
    tools = await client.discover_tools()

    assert {tool.name for tool in tools} == {
        "search_consultants",
        "search_projects",
        "search_opportunities",
    }


@pytest.mark.asyncio
async def test_call_unknown_tool_raises_tool_error() -> None:
    client = MockMcpClient()
    with pytest.raises(McpToolError):
        await client.call_tool("does_not_exist", {})


@pytest.mark.asyncio
async def test_call_search_consultants_returns_keyword_matches() -> None:
    client = MockMcpClient()
    records = await client.call_tool(
        "search_consultants", {"keywords": ["python", "ml"]}
    )

    assert records
    assert all("id" in r and "type" in r for r in records)
    assert records[0]["score"] >= records[-1]["score"]


@pytest.mark.asyncio
async def test_transient_failure_eventually_succeeds() -> None:
    client = MockMcpClient(transient_failures={"search_consultants": 1})

    with pytest.raises(McpTransientError):
        await client.call_tool("search_consultants", {"keywords": ["x"]})

    # Counter exhausted; second call succeeds.
    records = await client.call_tool("search_consultants", {"keywords": ["x"]})
    assert records


@pytest.mark.asyncio
async def test_permanent_failure_raises_tool_error() -> None:
    client = MockMcpClient(
        failures={"search_projects": McpToolError("validation", tool="search_projects")}
    )
    with pytest.raises(McpToolError):
        await client.call_tool("search_projects", {})
