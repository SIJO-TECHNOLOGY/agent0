"""Shared FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.mcp.client import McpClient
from app.services.search_service import SearchService


class McpClientUnavailableError(RuntimeError):
    """Raised when no MCP client has been bound to `app.state.mcp_client`.

    Translated to HTTP 503 with the standard error envelope by the
    handler registered in `app.main`. Fail-fast: never fall back to
    a mock client at request time.
    """


def get_mcp_client(request: Request) -> McpClient:
    """Return the MCP client bound to the FastAPI app.

    The client is bound during the FastAPI lifespan startup by
    `app.mcp.factory.create_mcp_client`. Tests may override
    `app.state.mcp_client` directly. There is intentionally no
    fallback: a missing client is a startup-or-config failure, not
    a runtime fallback to fake data.
    """
    client = getattr(request.app.state, "mcp_client", None)
    if client is None:
        raise McpClientUnavailableError(
            "app.state.mcp_client is not set; lifespan startup may have "
            "failed or been bypassed."
        )
    return client


def get_search_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    mcp_client: McpClient = Depends(get_mcp_client),
) -> SearchService:
    override = getattr(request.app.state, "search_service", None)
    if isinstance(override, SearchService):
        return override
    return SearchService(
        mcp_client=mcp_client,
        max_replan_attempts=settings.max_replan_attempts,
        mcp_max_retries=settings.mcp_max_retries,
    )
