"""Conversation persistence interface and shared value objects.

Every method is scoped by ``user_id`` (the Entra ``oid`` claim, or
``"dev"`` when auth is disabled): a user can never read, rename, or
delete another user's conversations — lookups simply miss.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

_TITLE_MAX_LENGTH = 40


def now_iso() -> str:
    """UTC timestamp in the API's usual `...Z` format."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_conversation_id() -> str:
    return f"conv_{uuid.uuid4().hex[:12]}"


def derive_title(first_message: str) -> str:
    """Automatic conversation title: the first message, tidied and capped."""
    flat = re.sub(r"\s+", " ", first_message or "").strip()
    if not flat:
        return "Nouvelle conversation"
    if len(flat) <= _TITLE_MAX_LENGTH:
        return flat
    return flat[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"


@dataclass(frozen=True)
class StoredMessage:
    role: str  # "user" | "assistant"
    content: str
    created_at: str
    ui: dict[str, object] | None = None


@dataclass(frozen=True)
class StoredConversation:
    id: str
    user_id: str
    title: str
    title_is_custom: bool
    created_at: str
    updated_at: str
    context: dict[str, object] = field(default_factory=dict)


class ConversationStore(Protocol):
    """Async persistence contract for per-user conversation history."""

    async def initialize(self) -> None:
        """Create schema / reach the backing service. Called at startup."""
        ...

    async def close(self) -> None:
        ...

    async def list_conversations(self, user_id: str) -> list[StoredConversation]:
        """All of the user's conversations, most recently updated first."""
        ...

    async def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> StoredConversation | None:
        ...

    async def get_messages(
        self, user_id: str, conversation_id: str
    ) -> list[StoredMessage]:
        """Messages in chronological order; [] when not found / not owner."""
        ...

    async def create_conversation(
        self, user_id: str, *, title: str | None = None
    ) -> StoredConversation:
        ...

    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> StoredConversation | None:
        """Set a custom title (survives auto-titling). None when not found."""
        ...

    async def delete_conversation(
        self, user_id: str, conversation_id: str
    ) -> bool:
        """Delete the conversation and its messages. False when not found."""
        ...

    async def delete_all_conversations(self, user_id: str) -> int:
        """Delete every conversation of the user; returns how many."""
        ...

    async def record_turn(
        self,
        user_id: str,
        conversation_id: str,
        *,
        user_message: str,
        assistant_message: str,
        assistant_ui: dict[str, object] | None = None,
        context: dict[str, object] | None = None,
    ) -> StoredConversation:
        """Persist one user/assistant exchange.

        Creates the conversation on first use (auto-titled from the
        user message), appends both messages, stores the assistant UI
        payload (candidate cards) so history can be re-rendered, saves
        the search context snapshot, and bumps ``updated_at``.
        """
        ...

    async def save_context(
        self, user_id: str, conversation_id: str, context: dict[str, object]
    ) -> None:
        """Persist the search-session context snapshot alone."""
        ...
