"""Durable per-user conversation persistence.

`ConversationStore` is the single interface the API talks to; the
backend is chosen by `CONVERSATION_STORE` (sqlite for local dev and
tests, azure_table for production). See `app.storage.factory`.
"""

from app.storage.store import (
    ConversationStore,
    StoredConversation,
    StoredMessage,
    derive_title,
)

__all__ = [
    "ConversationStore",
    "StoredConversation",
    "StoredMessage",
    "derive_title",
]
