"""Development-only MCP introspection endpoints.

These routes exist so a developer can hand-call an MCP tool through
the same client wiring the search workflow uses, without spinning up
a separate MCP client. They are **gated** behind
``ENABLE_MCP_DEBUG_ENDPOINTS`` and must never be enabled in shared
environments — they let arbitrary MCP tools run with arbitrary inputs.

Security posture:
- Returns 404 when the gate is disabled, so the endpoint cannot be
  fingerprinted in production.
- Uses the existing ``McpClient`` dependency; honours
  ``mcp_client_unavailable`` 503 envelope when the client isn't bound.
- The endpoint is intentionally narrow: one tool name, JSON inputs,
  normalized output. No discovery, no batching, no streaming.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_mcp_client
from app.config import Settings, get_settings
from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.models.api import ErrorEnvelope, ErrorPayload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp-debug"])


class McpDebugCallRequest(BaseModel):
    """JSON body for a debug MCP tool invocation."""

    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, object] = Field(default_factory=dict)


class McpDebugCallResponse(BaseModel):
    """Normalized output of a debug MCP tool invocation."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    inputs: dict[str, object]
    records: list[dict[str, object]]
    record_count: int = Field(ge=0)


def _ensure_enabled(settings: Settings) -> None:
    if not settings.enable_mcp_debug_endpoints:
        # 404 (not 403) so the route's existence is invisible when the
        # gate is off — matches the "production must not expose this"
        # posture.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post(
    "/api/mcp/tools/{tool_name}/call",
    response_model=McpDebugCallResponse,
    responses={
        404: {"description": "Debug endpoints are disabled."},
        503: {"model": ErrorEnvelope},
        502: {"model": ErrorEnvelope},
    },
)
async def debug_call_mcp_tool(
    tool_name: str,
    body: McpDebugCallRequest,
    settings: Settings = Depends(get_settings),
    mcp_client: McpClient = Depends(get_mcp_client),
) -> McpDebugCallResponse | JSONResponse:
    _ensure_enabled(settings)

    inputs = dict(body.inputs)
    logger.info(
        "mcp_debug.call",
        extra={"tool": tool_name, "input_keys": sorted(inputs.keys())},
    )
    try:
        records = await mcp_client.call_tool(tool_name, inputs)
    except McpTransientError as exc:
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "mcp_transient_error",
            f"Transient MCP failure: {exc}",
        )
    except McpToolError as exc:
        return _error_response(
            status.HTTP_502_BAD_GATEWAY,
            "mcp_tool_error",
            f"MCP tool {tool_name!r} failed: {exc}",
        )

    safe_records: list[dict[str, object]] = []
    for record in records:
        if isinstance(record, dict):
            safe_records.append(dict(record))
    return McpDebugCallResponse(
        tool=tool_name,
        inputs=inputs,
        records=safe_records,
        record_count=len(safe_records),
    )


def _error_response(
    status_code: int, code: str, message: str
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorPayload(code=code, message=message),
    )
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(envelope),
    )
