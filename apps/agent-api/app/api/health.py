"""Health (liveness) endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.config import get_settings
from app.models.api import HealthDependencies, HealthResponse, McpDependencyStatus

router = APIRouter(tags=["health"])


def _mcp_status_from_app(request: Request) -> McpDependencyStatus:
    """Return the lifespan-set MCP status, or a defensive fallback.

    The fallback only fires when the lifespan was bypassed (e.g. tests
    using `httpx.ASGITransport` without a `LifespanManager`) AND the test
    forgot to seed `app.state.mcp_status`. In that case we render
    `unavailable` rather than crashing the health endpoint.
    """
    status = getattr(request.app.state, "mcp_status", None)
    if isinstance(status, McpDependencyStatus):
        return status

    settings = get_settings()
    return McpDependencyStatus(
        status="unavailable",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error="mcp_status not initialized",
    )


@router.get("/api/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        dependencies=HealthDependencies(mcp=_mcp_status_from_app(request)),
    )
