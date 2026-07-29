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

from app.api.dependencies import McpClientUnavailableError, build_search_service
from app.config import Settings, get_settings
from app.models.api import SearchRequest
from app.services import conversation_memory as memory
from app.session import memory as session_memory
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
    ui_language: str | None = None,
) -> None:
    """Run the search; ensure the queue closes on every exit path."""
    try:
        await service.search_with_events(
            request,
            emitter,
            debug_mode=debug_mode,
            ui_language=ui_language,
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


def _inject_conversation_context(
    event_type: str,
    data: dict[str, object],
    conversation_id: str,
    *,
    search_page: int = 1,
    exclude_ids: set[str] | None = None,
) -> dict[str, object]:
    """Pin a stable conversation_id and bind results to the session memory.

    All candidates are displayed at once (no in-chat pagination). On a "more"
    turn (``search_page > 1``), candidates already shown in this conversation
    (``exclude_ids``) are dropped so only genuinely new profiles surface, and
    the session records the provider page + every id seen so far.
    """
    if event_type == "search_started":
        data["conversation_id"] = conversation_id
        return data
    if event_type != "final_response":
        return data

    data["conversation_id"] = conversation_id
    data["sessionId"] = conversation_id
    data["answer"] = data.get("answer") or data.get("message") or ""
    ui = data.get("ui")
    if isinstance(ui, dict) and ui.get("type") == "candidate_cards":
        shown = list(ui.get("candidates") or [])
        if exclude_ids:
            shown = [c for c in shown if str(c.get("id")) not in exclude_ids]
            ui["candidates"] = shown
            data["message"] = (
                f"{len(shown)} nouveaux candidats trouvés."
                if shown
                else "Aucun nouveau candidat trouvé pour cette recherche."
            )
            data["answer"] = data["message"]
        memory.store_results(conversation_id, shown)
        memory.mark_all_shown(conversation_id)
        # Track the provider page and every candidate id shown so far, so the
        # next "d'autres" fetches the following page and skips repeats.
        session = session_memory.get_or_create(conversation_id)
        prior_seen = {str(i) for i in (exclude_ids or set())}
        new_seen = prior_seen | {str(c.get("id")) for c in shown if c.get("id")}
        session.current_search["page"] = search_page
        session.current_search["seenIds"] = sorted(new_seen)
        session.touch()
    data["context"] = session_memory.context_payload(conversation_id)
    session_memory.append_message(conversation_id, role="assistant", content=str(data.get("message") or ""))
    return data


async def _stream(
    service: SearchService,
    request: SearchRequest,
    http_request: Request,
    *,
    conversation_id: str,
    debug_mode: bool = False,
    search_page: int = 1,
    exclude_ids: set[str] | None = None,
) -> AsyncIterator[str]:
    emitter = QueueEventEmitter()
    task = asyncio.create_task(
        _drive_workflow(
            service,
            request,
            emitter,
            debug_mode=debug_mode,
            ui_language=http_request.headers.get("accept-language"),
        )
    )
    try:
        async for event in emitter:
            # If the client went away, abandon the stream promptly so we
            # don't keep doing work for a dropped connection.
            if await http_request.is_disconnected():
                break
            event_type = str(event["type"])
            data = event["data"] if isinstance(event["data"], dict) else {}
            data = _inject_conversation_context(
                event_type, data, conversation_id,
                search_page=search_page, exclude_ids=exclude_ids,
            )
            yield _format_sse(event_type, data)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


async def _memory_operation_stream(
    conversation_id: str,
    operation: session_memory.SessionOperation,
) -> AsyncIterator[str]:
    """Serve filter/sort follow-ups from session candidates without MCP."""
    yield _format_sse(
        "search_started",
        {
            "conversation_id": conversation_id,
            "sessionId": conversation_id,
            "query": operation.effective_query,
            "planner_mode": "memory",
        },
    )
    candidates = operation.candidates or []
    session_memory.save_search_results(
        conversation_id,
        query=operation.session.last_user_query,
        effective_query=operation.effective_query,
        candidates=candidates,
        filters=operation.filters,
    )
    memory.store_results(conversation_id, candidates)
    memory.mark_all_shown(conversation_id)
    message = operation.message or (
        f"{len(candidates)} candidats correspondent à ta recherche."
        if candidates else "Aucun candidat ne correspond à ces critères."
    )
    session_memory.append_message(conversation_id, role="assistant", content=message)
    yield _format_sse(
        "final_response",
        {
            "conversation_id": conversation_id,
            "sessionId": conversation_id,
            "message": message,
            "answer": message,
            "ui": {"type": "candidate_cards", "candidates": candidates},
            "candidates": candidates,
            "context": session_memory.context_payload(conversation_id),
            "debug": {
                "sessionId": conversation_id,
                "isFollowUp": operation.is_follow_up,
                "shouldResetSearch": operation.should_reset_search,
                "currentSearch": dict(operation.session.current_search),
                "lastFilters": dict(operation.session.last_filters),
                "memoryCandidateCount": len(operation.session.current_candidates),
                "conversationHistorySize": len(operation.session.messages),
            },
        },
    )

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
    return build_search_service(mcp_client, settings, llm_planner=llm_planner)


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
    headers = {
        "Cache-Control": "no-cache",
        # Disable proxy buffering (nginx etc.) so events ship promptly.
        "X-Accel-Buffering": "no",
    }
    conversation_id = payload.sessionId or payload.conversation_id or memory.new_conversation_id()

    operation = session_memory.resolve_turn(conversation_id, payload.query)
    session_memory.append_message(conversation_id, role="user", content=payload.query)

    if operation.action in {"filter", "sort"} and operation.candidates is not None:
        return StreamingResponse(
            _memory_operation_stream(conversation_id, operation),
            media_type="text/event-stream",
            headers=headers,
        )

    service = _build_service(request, settings)
    if service is None:
        return StreamingResponse(
            _emit_mcp_unavailable(request, payload),
            media_type="text/event-stream",
            headers=headers,
        )

    session = operation.session
    exclude_ids: set[str] = set()
    search_page = 1
    if operation.action == "more" and session.current_search:
        # "d'autres profils" → SAME search, provider's NEXT page, and drop the
        # candidates already shown so only genuinely new profiles come back.
        search_page = int(session.current_search.get("page") or 1) + 1
        seen = session.current_search.get("seenIds")
        exclude_ids = {
            str(i) for i in (seen if isinstance(seen, list) else [])
        } or {str(c.get("id")) for c in session.current_candidates if c.get("id")}

    effective_query = operation.effective_query
    memory._queries[conversation_id] = effective_query
    extra_filters: dict[str, object] = {**payload.filters, **operation.filters}
    if search_page > 1:
        extra_filters["search_page"] = search_page
    payload = payload.model_copy(
        update={
            "query": effective_query,
            "filters": extra_filters,
            "conversation_id": conversation_id,
            "sessionId": conversation_id,
        }
    )

    debug_mode = _debug_mode_from_headers(request)
    return StreamingResponse(
        _stream(
            service, payload, request,
            conversation_id=conversation_id, debug_mode=debug_mode,
            search_page=search_page, exclude_ids=exclude_ids,
        ),
        media_type="text/event-stream",
        headers=headers,
    )





