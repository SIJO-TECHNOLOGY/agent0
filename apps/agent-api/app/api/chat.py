"""Frontend-compatible chat and lightweight conversation endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_search_service
from app.models.api import (
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationSummary,
    SearchRequest,
    SearchResponse,
)
from app.services.search_service import SearchService

router = APIRouter(tags=["chat"])

_CONVERSATIONS: dict[str, ConversationDetail] = {}
_CANDIDATES: dict[str, dict[str, object]] = {}


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


def _chat_response_from_search(
    *,
    conversation_id: str,
    search: SearchResponse,
    debug: dict[str, object] | None = None,
) -> ChatResponse:
    # Non-candidate UIs (e.g. clarification) carry no candidates.
    ui_candidates = getattr(search.ui, "candidates", None) or []
    candidates = [candidate.model_dump() for candidate in ui_candidates]
    for candidate in candidates:
        _CANDIDATES[str(candidate["id"])] = candidate

    return ChatResponse(
        conversation_id=conversation_id,
        message=search.message,
        ui=search.ui.model_dump(),
        candidates=candidates,
        debug=debug or {},
    )


def _upsert_conversation(conversation_id: str, title: str) -> None:
    now = _now()
    existing = _CONVERSATIONS.get(conversation_id)
    if existing:
        _CONVERSATIONS[conversation_id] = existing.model_copy(update={"updated_at": now})
        return
    _CONVERSATIONS[conversation_id] = ConversationDetail(
        id=conversation_id,
        title=title or "Nouvelle conversation",
        created_at=now,
        updated_at=now,
        messages=[],
    )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    debug: bool = Query(default=False),
    service: SearchService = Depends(get_search_service),
) -> ChatResponse:
    query = _query_from_payload(payload)
    conversation_id = _conversation_id(payload.conversation_id)
    if debug:
        emitter = _CaptureEventEmitter()
        search = await service.search_with_events(
            SearchRequest(query=query, filters={}),
            emitter,
            debug_mode=True,
        )
        debug_payload: dict[str, object] = {
            "planner_mode": "llm" if service.llm_planner is not None else "deterministic",
            "events": emitter.events,
        }
    else:
        search = await service.search(SearchRequest(query=query, filters={}))
        debug_payload = {}
    response = _chat_response_from_search(
        conversation_id=conversation_id,
        search=search,
        debug=debug_payload,
    )
    _upsert_conversation(conversation_id, query[:80])
    return response


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    return [
        ConversationSummary(**conversation.model_dump(exclude={"messages"}))
        for conversation in sorted(
            _CONVERSATIONS.values(), key=lambda item: item.updated_at, reverse=True
        )
    ]


@router.post(
    "/api/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreateRequest,
) -> ConversationSummary:
    conversation_id = _conversation_id(None)
    _upsert_conversation(conversation_id, payload.title)
    conversation = _CONVERSATIONS[conversation_id]
    return ConversationSummary(**conversation.model_dump(exclude={"messages"}))


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    conversation = _CONVERSATIONS.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return conversation


@router.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str) -> None:
    _CONVERSATIONS.pop(conversation_id, None)


@router.get("/api/candidates/{candidate_id}")
async def get_candidate(candidate_id: str) -> dict[str, object]:
    candidate = _CANDIDATES.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return candidate
