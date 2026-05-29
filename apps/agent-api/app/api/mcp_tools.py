"""GET /api/mcp/tools — list MCP tools discovered from the connected server.

This is a thin development/debug endpoint that delegates to the
bound `McpClient.discover_tools()`. It honours the existing wiring:
in mock mode it returns the mock catalogue; in real mode it returns
whatever the connected MCP server advertises. When the MCP client
is not bound, the standard `mcp_client_unavailable` 503 envelope is
returned via the global handler registered in `app.main`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.dependencies import get_mcp_client
from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.models.api import ErrorEnvelope, ErrorPayload, McpToolsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])


@router.get(
    "/api/mcp/tools",
    response_model=McpToolsResponse,
    responses={
        503: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
)
async def list_mcp_tools(
    mcp_client: McpClient = Depends(get_mcp_client),
) -> McpToolsResponse | JSONResponse:
    try:
        tools = await mcp_client.discover_tools()
    except McpTransientError as exc:
        logger.warning("mcp_tools.transient_failure", extra={"error": str(exc)})
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="mcp_client_unavailable",
                message=(
                    "The MCP server is currently unreachable. Tool discovery "
                    "cannot be completed."
                ),
            )
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(envelope),
        )
    except McpToolError as exc:
        logger.exception("mcp_tools.discovery_failed")
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="mcp_tool_error",
                message=f"MCP tool discovery failed: {exc}",
            )
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=jsonable_encoder(envelope),
        )

    return McpToolsResponse(tools=list(tools), count=len(tools))
