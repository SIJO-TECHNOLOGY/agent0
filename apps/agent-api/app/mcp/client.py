"""MCP client abstraction.

The MVP ships a mocked implementation (`MockMcpClient`). A real
transport (stdio, SSE, or HTTP) will plug in behind this interface
without changing the agent or service layers.
"""

from __future__ import annotations

from typing import Protocol

from app.models.tools import McpTool


class McpClientError(Exception):
    """Base class for MCP client errors."""

    def __init__(self, message: str, *, tool: str | None = None) -> None:
        super().__init__(message)
        self.tool = tool


class McpToolError(McpClientError):
    """Raised when a tool returns a validation or non-retryable error."""


class McpTransientError(McpClientError):
    """Raised for transient failures that may be safe to retry."""


class McpClient(Protocol):
    """Abstract async MCP client."""

    async def discover_tools(self) -> list[McpTool]:
        """Return the catalogue of available MCP tools."""
        ...

    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        """Execute a tool and return a list of raw result records.

        Implementations must raise `McpToolError` for non-retryable
        problems and `McpTransientError` for transient failures.
        """
        ...
