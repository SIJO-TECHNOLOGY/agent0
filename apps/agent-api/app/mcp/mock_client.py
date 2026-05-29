"""In-memory mock MCP client for MVP development and tests.

The mock client exposes a stable tool catalogue and returns
deterministic fake responses so the workflow can be exercised
end-to-end without a live MCP server or BoondManager access.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.mcp.result_normalizer import coerce_records
from app.models.tools import McpTool

ToolHandler = Callable[[dict[str, object]], Awaitable[list[dict[str, object]]]]


DEFAULT_TOOLS: Final[list[McpTool]] = [
    McpTool(
        name="search_consultants",
        description="Search BoondManager consultants by skills, availability, seniority.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "available_from": {"type": "string"},
                "seniority": {"type": "string"},
            },
        },
    ),
    McpTool(
        name="search_projects",
        description="Search BoondManager projects by status, client, or technology.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string"},
            },
        },
    ),
    McpTool(
        name="search_opportunities",
        description="Search BoondManager opportunities by stage, owner, or amount.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "stage": {"type": "string"},
            },
        },
    ),
]


async def _default_consultants_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    keywords = _as_keyword_list(inputs.get("keywords"))
    if not keywords:
        return [
            {
                "id": "c-001",
                "type": "consultant",
                "title": "Available senior consultant",
                "snippet": "Generic match: no keyword filter provided.",
                "score": 0.4,
            }
        ]
    base_score = min(0.95, 0.6 + 0.1 * len(keywords))
    return [
        {
            "id": f"c-{i + 1:03d}",
            "type": "consultant",
            "title": f"Consultant skilled in {keywords[0]}",
            "snippet": f"Matches keywords: {', '.join(keywords)}",
            "score": round(base_score - i * 0.05, 2),
        }
        for i in range(min(3, max(1, len(keywords))))
    ]


async def _default_projects_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    keywords = _as_keyword_list(inputs.get("keywords"))
    if not keywords:
        return []
    return [
        {
            "id": "p-001",
            "type": "project",
            "title": f"Project using {keywords[0]}",
            "snippet": "Active project matching keyword filter.",
            "score": 0.7,
        }
    ]


async def _default_opportunities_handler(
    inputs: dict[str, object],
) -> list[dict[str, object]]:
    return []


def _as_keyword_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int))]
    if isinstance(value, str) and value:
        return [value]
    return []


class MockMcpClient(McpClient):
    """A deterministic MCP client used in MVP development and tests."""

    def __init__(
        self,
        *,
        tools: list[McpTool] | None = None,
        handlers: dict[str, ToolHandler] | None = None,
        failures: dict[str, Exception] | None = None,
        transient_failures: dict[str, int] | None = None,
        latency_seconds: float = 0.0,
    ) -> None:
        self._tools = list(tools) if tools is not None else list(DEFAULT_TOOLS)
        self._handlers: dict[str, ToolHandler] = {
            "search_consultants": _default_consultants_handler,
            "search_projects": _default_projects_handler,
            "search_opportunities": _default_opportunities_handler,
        }
        if handlers:
            self._handlers.update(handlers)
        self._failures = dict(failures or {})
        self._transient_remaining = dict(transient_failures or {})
        self._latency_seconds = latency_seconds

    async def discover_tools(self) -> list[McpTool]:
        if self._latency_seconds:
            await asyncio.sleep(self._latency_seconds)
        return list(self._tools)

    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        if self._latency_seconds:
            await asyncio.sleep(self._latency_seconds)

        if tool in self._failures:
            raise self._failures[tool]

        if self._transient_remaining.get(tool, 0) > 0:
            self._transient_remaining[tool] -= 1
            raise McpTransientError(
                f"transient failure for tool {tool!r}", tool=tool
            )

        handler = self._handlers.get(tool)
        if handler is None:
            raise McpToolError(f"unknown tool: {tool}", tool=tool)
        raw = await handler(inputs)
        # Apply the same envelope-unwrap that the real RemoteMcpClient
        # runs, so test fixtures can use realistic wrapper shapes (e.g.
        # ``{"candidates": [...], "meta": {...}}``) and see the same
        # downstream behaviour as production.
        return coerce_records(raw, tool=tool)
