"""POST /api/search/stream — Server-Sent Events progress channel.

This is the *external* transport between the frontend UI and the Agent
API. It is unrelated to the Streamable HTTP transport the Agent API
uses internally to speak MCP. The frontend never sees raw MCP frames;
only sanitized progress events.

A background task drives the workflow with a ``QueueEventEmitter``
while the route formats each queued event as an SSE frame:

    event: <event_type>
    data: <json payload>

The stream always ends with a single ``final_response`` event on
success, or a single ``search_failed`` event on failure (no leaked
exception text).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import McpClientUnavailableError
from app.config import Settings, get_settings
from app.models.api import SearchRequest
from app.services.event_emitter import QueueEventEmitter
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


def _format_sse(event_type: str, payload: dict[str, object]) -> str:
    """Render one SSE frame. The JSON payload is single-line by design."""
    # `ensure_ascii=False` keeps unicode (names, French labels, ...)
    # readable on the wire. `default=str` is a safety net for things
    # like enum values that occasionally sneak through.
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {body}\n\n"


async def _drive_workflow(
    service: SearchService,
    request: SearchRequest,
    emitter: QueueEventEmitter,
    *,
    debug_mode: bool = False,
) -> None:
    """Run the search; ensure the queue closes on every exit path."""
    try:
        await service.search_with_events(
            request, emitter, debug_mode=debug_mode
        )
    except McpClientUnavailableError:
        logger.info("search_stream.mcp_unavailable")
        await emitter.emit(
            "search_failed",
            {
                "error": {
                    "code": "mcp_client_unavailable",
                    "message": (
                        "The MCP client is not initialized. The Agent API "
                        "cannot serve search requests until an MCP client "
                        "is bound."
                    ),
                    "details": {},
                }
            },
        )
    except Exception:  # noqa: BLE001 — never leak provider stack traces
        logger.exception("search_stream.unexpected_error")
        await emitter.emit(
            "search_failed",
            {
                "error": {
                    "code": "internal_error",
                    "message": (
                        "An internal error occurred while processing the "
                        "search."
                    ),
                    "details": {},
                }
            },
        )
    finally:
        emitter.close()


async def _stream(
    service: SearchService,
    request: SearchRequest,
    http_request: Request,
    *,
    debug_mode: bool = False,
) -> AsyncIterator[str]:
    emitter = QueueEventEmitter()
    task = asyncio.create_task(
        _drive_workflow(service, request, emitter, debug_mode=debug_mode)
    )
    try:
        async for event in emitter:
            # If the client went away, abandon the stream promptly so we
            # don't keep doing work for a dropped connection.
            if await http_request.is_disconnected():
                break
            yield _format_sse(
                str(event["type"]),
                event["data"] if isinstance(event["data"], dict) else {},
            )
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


def _build_service(
    request: Request, settings: Settings
) -> SearchService | None:
    """Build a SearchService from app.state without going through the
    Depends chain that would 503 on a missing MCP client.

    Returns ``None`` if the MCP client isn't bound — the route then
    emits a ``search_failed`` SSE event instead of returning a JSON 503,
    which is what the stream contract requires.
    """
    override = getattr(request.app.state, "search_service", None)
    if isinstance(override, SearchService):
        return override

    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None:
        return None

    llm_planner = getattr(request.app.state, "llm_planner", None)
    return SearchService(
        mcp_client=mcp_client,
        max_replan_attempts=settings.max_replan_attempts,
        mcp_max_retries=settings.mcp_max_retries,
        llm_planner=llm_planner,
        max_plan_steps=settings.llm_max_plan_steps,
    )


async def _emit_mcp_unavailable(
    request: Request, payload: SearchRequest
) -> AsyncIterator[str]:
    """Single-event stream used when the MCP client is unbound."""
    yield _format_sse(
        "search_failed",
        {
            "error": {
                "code": "mcp_client_unavailable",
                "message": (
                    "The MCP client is not initialized. The Agent API "
                    "cannot serve search requests until an MCP client "
                    "is bound."
                ),
                "details": {},
            }
        },
    )


def _debug_mode_from_headers(request: Request) -> bool:
    """Opt-in stream debug mode via the ``X-Agent-Debug: true`` header.

    Debug mode causes nodes to attach sanitized previews of MCP records
    to stream events. The truncated previews are still safe to ship but
    are off by default to keep normal traffic free of any record values.
    """
    raw = request.headers.get("X-Agent-Debug", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@router.post("/api/search/stream")
async def search_stream(
    payload: SearchRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    service = _build_service(request, settings)
    headers = {
        "Cache-Control": "no-cache",
        # Disable proxy buffering (nginx etc.) so events ship promptly.
        "X-Accel-Buffering": "no",
    }
    if service is None:
        return StreamingResponse(
            _emit_mcp_unavailable(request, payload),
            media_type="text/event-stream",
            headers=headers,
        )
    debug_mode = _debug_mode_from_headers(request)
    return StreamingResponse(
        _stream(service, payload, request, debug_mode=debug_mode),
        media_type="text/event-stream",
        headers=headers,
    )
