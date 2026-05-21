"""Factory for selecting and constructing the MCP client implementation.

The factory is the single place that decides between the in-memory
mock and the real remote MCP client. Runtime code MUST go through
this factory; importing `MockMcpClient` directly from application
wiring would re-introduce the silent-fallback risk.
"""

from __future__ import annotations

from typing import Final

from app.config.settings import Settings
from app.mcp.client import McpClient
from app.mcp.mock_client import MockMcpClient
from app.mcp.remote_client import RemoteMcpClient

SUPPORTED_TRANSPORTS: Final[frozenset[str]] = frozenset({"streamable_http"})


class McpClientNotImplementedError(RuntimeError):
    """Raised when the requested MCP client configuration is unavailable.

    Surfaces as a fail-fast startup error so the API never silently
    serves mock data when the operator intended to use a real MCP
    server (or asked for a transport that is not yet supported).
    """


def create_mcp_client(settings: Settings) -> McpClient:
    """Return the MCP client implementation selected by settings.

    - `use_mock_mcp=True` -> in-memory `MockMcpClient` for local/dev/tests.
    - `use_mock_mcp=False` -> `RemoteMcpClient` over the configured transport.

    `mcp_server_url` and `mcp_transport` are validated here so
    misconfiguration is caught at startup, not at the first request.
    """
    if settings.use_mock_mcp:
        return MockMcpClient()

    if not settings.mcp_server_url:
        raise McpClientNotImplementedError(
            "USE_MOCK_MCP=false requires MCP_SERVER_URL to point at a real "
            "MCP server, but it is not configured."
        )

    transport = settings.mcp_transport
    if transport not in SUPPORTED_TRANSPORTS:
        supported = ", ".join(sorted(SUPPORTED_TRANSPORTS))
        raise McpClientNotImplementedError(
            f"Unsupported MCP_TRANSPORT={transport!r}. "
            f"Supported transports: {supported}."
        )

    return RemoteMcpClient(
        url=settings.mcp_server_url,
        timeout_seconds=settings.mcp_timeout_seconds,
    )
