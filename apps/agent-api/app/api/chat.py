"""Frontend-compatible chat and lightweight conversation endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import AuthenticatedUser, get_current_user
from app.api.dependencies import get_conversation_store, get_search_service
from app.models.api import (
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationRenameRequest,
    ConversationSummary,
    SearchRequest,
    SearchResponse,
    SessionResetRequest,
    SessionResetResponse,
)
from app.session import memory as session_memory
from app.session.rehydrate import ensure_session_hydrated
from app.services import conversation_memory as memory
from app.services.search_service import SearchService
from app.storage import ConversationStore, StoredConversation

router = APIRouter(tags=["chat"])

_CANDIDATES: dict[str, dict[str, object]] = {}

_PAGE_SIZE = memory.PAGE_SIZE
_combine_query = memory.combine_query
_is_more_request = memory.is_more_request
_CONVERSATION_QUERIES = memory._queries
_CONVERSATION_RESULTS = memory._pools


def _serve_page(conversation_id: str, *, debug: dict[str, object] | None = None) -> ChatResponse:
    """Return the next page of the conversation's stored result pool."""
    info = memory.next_page(conversation_id)
    for candidate in info["candidates"]:
        _CANDIDATES[str(candidate.get("id"))] = candidate
    message = memory.pagination_message(info)
    return ChatResponse(
        conversation_id=conversation_id,
        sessionId=conversation_id,
        message=message,
        answer=message,
        ui={"type": "candidate_cards", "candidates": info["candidates"]},
        candidates=info["candidates"],
        context=session_memory.context_payload(conversation_id),
        debug=debug or {},
    )


class _CaptureEventEmitter:
    """Small debug-only emitter used by /api/chat?debug=true."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event_type: str, payload: dict[str, object]) -> None:
        if event_type in {
            "search_started",
            "tools_discovered",
            "plan_created",
            "plan_validated",
            "tool_call_started",
            "tool_call_completed",
        }:
            self.events.append({"type": event_type, "data": payload})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _conversation_id(value: str | None) -> str:
    return value or f"conv_{uuid.uuid4().hex[:12]}"


def _session_id_from_payload(payload: ChatRequest) -> str:
    return payload.sessionId or payload.conversation_id or _conversation_id(None)


def _query_from_payload(payload: ChatRequest) -> str:
    if payload.message:
        return payload.message

    interaction = payload.interaction or {}
    values = interaction.get("values")
    if isinstance(values, dict) and values:
        parts = [str(value) for value in values.values() if value not in (None, "")]
        if parts:
            return " ".join(parts)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="message or interaction values are required",
    )


def _debug_payload(
    *,
    service: SearchService,
    effective_query: str,
    operation: session_memory.SessionOperation,
    events: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "planner_mode": "llm" if service.llm_planner is not None else "deterministic",
        "events": events or [],
        "effective_query": effective_query,
        "sessionId": operation.session.session_id,
        "isFollowUp": operation.is_follow_up,
        "shouldResetSearch": operation.should_reset_search,
        "currentSearch": dict(operation.session.current_search),
        "lastFilters": dict(operation.session.last_filters),
        "memoryCandidateCount": len(operation.session.current_candidates),
        "conversationHistorySize": len(operation.session.messages),
    }


def _chat_response_from_search(
    *,
    conversation_id: str,
    search: SearchResponse,
    debug: dict[str, object] | None = None,
) -> ChatResponse:
    ui_candidates = getattr(search.ui, "candidates", None) or []
    candidates = [candidate.model_dump() for candidate in ui_candidates]
    for candidate in candidates:
        _CANDIDATES[str(candidate["id"])] = candidate

    message = search.message
    return ChatResponse(
        conversation_id=conversation_id,
        sessionId=conversation_id,
        message=message,
        answer=message,
        ui=search.ui.model_dump(),
        candidates=candidates,
        context=search.context or session_memory.context_payload(conversation_id),
        debug=debug or {},
    )


def _response_from_memory_operation(
    conversation_id: str,
    operation: session_memory.SessionOperation,
    *,
    debug: dict[str, object] | None = None,
) -> ChatResponse:
    candidates = operation.candidates or []
    session_memory.save_search_results(
        conversation_id,
        query=operation.session.last_user_query,
        effective_query=operation.effective_query,
        candidates=candidates,
        filters=operation.filters,
    )
    memory.store_results(conversation_id, candidates)
    if debug is not None:
        debug.update({
            "currentSearch": dict(session_memory.get_or_create(conversation_id).current_search),
            "lastFilters": dict(session_memory.get_or_create(conversation_id).last_filters),
            "memoryCandidateCount": len(session_memory.get_or_create(conversation_id).current_candidates),
            "conversationHistorySize": len(session_memory.get_or_create(conversation_id).messages),
        })
    info = memory.next_page(conversation_id)
    message = operation.message or memory.pagination_message(info)
    return ChatResponse(
        conversation_id=conversation_id,
        sessionId=conversation_id,
        message=message,
        answer=message,
        ui={"type": "candidate_cards", "candidates": info["candidates"]},
        candidates=info["candidates"],
        context=session_memory.context_payload(conversation_id),
        debug=debug or {},
    )


def _summary(conversation: StoredConversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def _persist_turn(
    store: ConversationStore,
    user: AuthenticatedUser,
    conversation_id: str,
    *,
    user_message: str,
    assistant_message: str,
    assistant_ui: dict[str, object] | None = None,
) -> None:
    """Record one exchange both in session memory and in the durable store."""
    session_memory.append_message(conversation_id, role="user", content=user_message)
    session_memory.append_message(
        conversation_id, role="assistant", content=assistant_message
    )
    await store.record_turn(
        user.oid,
        conversation_id,
        user_message=user_message,
        assistant_message=assistant_message,
        assistant_ui=assistant_ui,
        context=session_memory.context_snapshot(conversation_id),
    )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    debug: bool = Query(default=False),
    service: SearchService = Depends(get_search_service),
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ChatResponse:
    message = _query_from_payload(payload)
    conversation_id = _session_id_from_payload(payload)
    debug_enabled = debug or payload.debug
    await ensure_session_hydrated(store, user.oid, conversation_id)
    operation = session_memory.resolve_turn(conversation_id, message)

    if operation.action == "more" and memory.has_pool(conversation_id):
        debug_payload = _debug_payload(
            service=service, effective_query=operation.effective_query, operation=operation
        ) if debug_enabled else {}
        response = _serve_page(conversation_id, debug=debug_payload)
        await _persist_turn(
            store, user, conversation_id,
            user_message=message, assistant_message=response.message,
            assistant_ui=response.ui,
        )
        return response

    if operation.action in {"filter", "sort"} and operation.candidates is not None:
        debug_payload = _debug_payload(
            service=service, effective_query=operation.effective_query, operation=operation
        ) if debug_enabled else {}
        response = _response_from_memory_operation(
            conversation_id, operation, debug=debug_payload
        )
        await _persist_turn(
            store, user, conversation_id,
            user_message=message, assistant_message=response.message,
            assistant_ui=response.ui,
        )
        return response

    if debug_enabled:
        emitter = _CaptureEventEmitter()
        search = await service.search_with_events(
            SearchRequest(
                query=operation.effective_query,
                filters=operation.filters,
                conversation_id=conversation_id,
                sessionId=conversation_id,
            ),
            emitter,
            debug_mode=True,
        )
        debug_payload = _debug_payload(
            service=service,
            effective_query=operation.effective_query,
            operation=operation,
            events=emitter.events,
        )
    else:
        search = await service.search(
            SearchRequest(
                query=operation.effective_query,
                filters=operation.filters,
                conversation_id=conversation_id,
                sessionId=conversation_id,
            )
        )
        debug_payload = {}

    _CONVERSATION_QUERIES[conversation_id] = operation.effective_query

    if getattr(search.ui, "type", None) == "clarification":
        _CONVERSATION_RESULTS.pop(conversation_id, None)
        response = _chat_response_from_search(
            conversation_id=conversation_id, search=search, debug=debug_payload
        )
        await _persist_turn(
            store, user, conversation_id,
            user_message=message, assistant_message=search.message,
            assistant_ui=response.ui,
        )
        return response

    full = [candidate.model_dump() for candidate in getattr(search.ui, "candidates", [])]
    if not full:
        _CONVERSATION_RESULTS.pop(conversation_id, None)
        response = _chat_response_from_search(
            conversation_id=conversation_id, search=search, debug=debug_payload
        )
        await _persist_turn(
            store, user, conversation_id,
            user_message=message, assistant_message=search.message,
            assistant_ui=response.ui,
        )
        return response

    memory.store_results(conversation_id, full)
    response = _serve_page(conversation_id, debug=debug_payload)
    await _persist_turn(
        store, user, conversation_id,
        user_message=message, assistant_message=response.message,
        assistant_ui=response.ui,
    )
    return response


@router.post("/api/chat/session/reset", response_model=SessionResetResponse)
async def reset_chat_session(payload: SessionResetRequest) -> SessionResetResponse:
    session_id = payload.sessionId or payload.conversation_id
    if not session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sessionId is required")
    memory.reset(session_id)
    return SessionResetResponse(sessionId=session_id)


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[ConversationSummary]:
    return [_summary(c) for c in await store.list_conversations(user.oid)]


@router.post(
    "/api/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationSummary:
    conversation = await store.create_conversation(user.oid, title=payload.title)
    session_memory.get_or_create(conversation.id)
    return _summary(conversation)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationDetail:
    conversation = await store.get_conversation(user.oid, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    messages = await store.get_messages(user.oid, conversation_id)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            {
                "role": message.role,
                "content": message.content,
                "at": message.created_at,
                **({"ui": message.ui} if message.ui else {}),
            }
            for message in messages
        ],
    )


@router.patch(
    "/api/conversations/{conversation_id}", response_model=ConversationSummary
)
async def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationSummary:
    conversation = await store.rename_conversation(
        user.oid, conversation_id, payload.title
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _summary(conversation)


@router.delete(
    "/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    deleted = await store.delete_conversation(user.oid, conversation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    memory.reset(conversation_id)
    session_memory.reset(conversation_id)


@router.delete("/api/conversations", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    conversations = await store.list_conversations(user.oid)
    await store.delete_all_conversations(user.oid)
    for conversation in conversations:
        memory.reset(conversation.id)
        session_memory.reset(conversation.id)


@router.get("/api/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> dict[str, object]:
    candidate = _CANDIDATES.get(candidate_id)
    if candidate is not None:
        return candidate
    # The in-process cache is empty after a restart: fall back to the
    # cards persisted in the user's conversations, most recent first.
    for conversation in await store.list_conversations(user.oid):
        for message in reversed(
            await store.get_messages(user.oid, conversation.id)
        ):
            ui = message.ui or {}
            candidates = ui.get("candidates")
            if not isinstance(candidates, list):
                continue
            for card in candidates:
                if isinstance(card, dict) and str(card.get("id")) == candidate_id:
                    _CANDIDATES[candidate_id] = card
                    return card
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

