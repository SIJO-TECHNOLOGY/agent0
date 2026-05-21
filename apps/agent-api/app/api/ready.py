"""Readiness endpoint.

Liveness (`/api/health`) only proves the process is alive. Readiness
(`/api/ready`) reports whether the Agent API can actually serve
search requests right now — i.e. whether an MCP client is bound.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app import __version__
from app.api.health import _mcp_status_from_app
from app.models.api import HealthDependencies, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/ready")
async def ready(request: Request) -> JSONResponse:
    mcp = _mcp_status_from_app(request)
    body = HealthResponse(
        status="ok" if mcp.status != "unavailable" else "unavailable",
        version=__version__,
        dependencies=HealthDependencies(mcp=mcp),
    )
    code = (
        status.HTTP_200_OK
        if mcp.status != "unavailable"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=code, content=jsonable_encoder(body))
