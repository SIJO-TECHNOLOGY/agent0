"""Choose the ConversationStore backend from settings.

Mirrors the MCP factory philosophy: the backend is an explicit
configuration decision, never a silent runtime fallback.
"""

from __future__ import annotations

from app.config import Settings
from app.storage.store import ConversationStore


class ConversationStoreConfigurationError(RuntimeError):
    """Raised at startup when the store configuration is invalid."""


def create_conversation_store(settings: Settings) -> ConversationStore:
    backend = settings.conversation_store.strip().lower()
    if backend == "sqlite":
        from app.storage.sqlite_store import SqliteConversationStore

        return SqliteConversationStore(settings.sqlite_db_path)
    if backend == "azure_table":
        if not (
            settings.azure_storage_connection_string
            or settings.azure_storage_account_url
        ):
            raise ConversationStoreConfigurationError(
                "CONVERSATION_STORE=azure_table requires "
                "AZURE_STORAGE_CONNECTION_STRING or "
                "AZURE_STORAGE_ACCOUNT_URL."
            )
        from app.storage.azure_table_store import AzureTableConversationStore

        return AzureTableConversationStore(
            connection_string=settings.azure_storage_connection_string,
            account_url=settings.azure_storage_account_url,
        )
    raise ConversationStoreConfigurationError(
        f"Unknown CONVERSATION_STORE '{settings.conversation_store}'. "
        "Supported: sqlite, azure_table."
    )
