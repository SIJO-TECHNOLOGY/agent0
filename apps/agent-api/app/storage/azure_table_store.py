"""Azure Table Storage implementation of ConversationStore.

Production backend: serverless, in-tenant, durable, ~free at this
scale. Layout:

- table ``agent0conversations``: PartitionKey = user oid,
  RowKey = conversation id.
- table ``agent0messages``: PartitionKey = conversation id,
  RowKey = zero-padded nanosecond timestamp + sequence, so a plain
  partition scan returns messages in chronological order.

Auth: ``AZURE_STORAGE_CONNECTION_STRING`` when provided (local /
simple setups), otherwise ``AZURE_STORAGE_ACCOUNT_URL`` with
DefaultAzureCredential (managed identity in Container Apps — no
secret; the identity needs the "Storage Table Data Contributor"
role).

String properties are capped at 64 KB in Table Storage, so the
assistant UI payload (candidate cards JSON) is split across chunked
properties ``ui_json_00..``; total entity size stays well under the
1 MB entity limit for realistic result sets.
"""

from __future__ import annotations

import json
import logging
import time
from itertools import count

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.data.tables.aio import TableServiceClient

from app.storage.store import (
    StoredConversation,
    StoredMessage,
    derive_title,
    new_conversation_id,
    now_iso,
)

logger = logging.getLogger(__name__)

_CONVERSATIONS_TABLE = "agent0conversations"
_MESSAGES_TABLE = "agent0messages"

# 64 KB per string property means 32 K UTF-16 code units; stay under it.
_CHUNK_CHARS = 30_000
_MAX_CHUNKS = 30

_row_seq = count()


def _message_row_key() -> str:
    """Sortable, collision-free RowKey: padded ns timestamp + sequence."""
    return f"{time.time_ns():020d}-{next(_row_seq) % 1000:03d}"


def _pack_json(entity: dict[str, object], prefix: str, payload: dict[str, object] | None) -> None:
    if not payload:
        return
    text = json.dumps(payload, ensure_ascii=False)
    chunks = [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]
    if len(chunks) > _MAX_CHUNKS:
        logger.warning(
            "conversation_store.azure.payload_truncated",
            extra={"chunks": len(chunks)},
        )
        chunks = chunks[:_MAX_CHUNKS]
    for index, chunk in enumerate(chunks):
        entity[f"{prefix}_{index:02d}"] = chunk


def _unpack_json(entity: dict[str, object], prefix: str) -> dict[str, object]:
    parts: list[str] = []
    for index in range(_MAX_CHUNKS):
        value = entity.get(f"{prefix}_{index:02d}")
        if value is None:
            break
        parts.append(str(value))
    if not parts:
        return {}
    try:
        parsed = json.loads("".join(parts))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _conversation_from_entity(entity: dict[str, object]) -> StoredConversation:
    return StoredConversation(
        id=str(entity["RowKey"]),
        user_id=str(entity["PartitionKey"]),
        title=str(entity.get("title") or "Nouvelle conversation"),
        title_is_custom=bool(entity.get("title_is_custom")),
        context=_unpack_json(entity, "context_json"),
        created_at=str(entity.get("created_at") or ""),
        updated_at=str(entity.get("updated_at") or ""),
    )


class AzureTableConversationStore:
    def __init__(
        self,
        *,
        connection_string: str | None = None,
        account_url: str | None = None,
    ) -> None:
        if not connection_string and not account_url:
            raise ValueError(
                "AzureTableConversationStore needs a connection string or "
                "an account URL."
            )
        self._connection_string = connection_string
        self._account_url = account_url
        self._service: TableServiceClient | None = None
        self._credential = None

    async def initialize(self) -> None:
        if self._connection_string:
            self._service = TableServiceClient.from_connection_string(
                self._connection_string
            )
        else:
            from azure.identity.aio import DefaultAzureCredential

            self._credential = DefaultAzureCredential()
            self._service = TableServiceClient(
                endpoint=self._account_url, credential=self._credential
            )
        for table in (_CONVERSATIONS_TABLE, _MESSAGES_TABLE):
            try:
                await self._service.create_table(table)
            except ResourceExistsError:
                pass
        logger.info("conversation_store.azure.ready")

    async def close(self) -> None:
        if self._service is not None:
            await self._service.close()
            self._service = None
        if self._credential is not None:
            await self._credential.close()
            self._credential = None

    def _table(self, name: str):
        if self._service is None:
            raise RuntimeError(
                "AzureTableConversationStore used before initialize()"
            )
        return self._service.get_table_client(name)

    async def list_conversations(self, user_id: str) -> list[StoredConversation]:
        client = self._table(_CONVERSATIONS_TABLE)
        entities = client.query_entities(
            "PartitionKey eq @user", parameters={"user": user_id}
        )
        conversations = [_conversation_from_entity(e) async for e in entities]
        conversations.sort(key=lambda c: c.updated_at, reverse=True)
        return conversations

    async def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> StoredConversation | None:
        client = self._table(_CONVERSATIONS_TABLE)
        try:
            entity = await client.get_entity(user_id, conversation_id)
        except ResourceNotFoundError:
            return None
        return _conversation_from_entity(entity)

    async def get_messages(
        self, user_id: str, conversation_id: str
    ) -> list[StoredMessage]:
        # Ownership gate: the messages partition key is the conversation
        # id, so verify the conversation belongs to this user first.
        if await self.get_conversation(user_id, conversation_id) is None:
            return []
        client = self._table(_MESSAGES_TABLE)
        entities = client.query_entities(
            "PartitionKey eq @conv", parameters={"conv": conversation_id}
        )
        rows = [entity async for entity in entities]
        rows.sort(key=lambda e: str(e["RowKey"]))
        return [
            StoredMessage(
                role=str(entity.get("role") or ""),
                content=str(entity.get("content") or ""),
                ui=_unpack_json(entity, "ui_json") or None,
                created_at=str(entity.get("created_at") or ""),
            )
            for entity in rows
        ]

    async def create_conversation(
        self, user_id: str, *, title: str | None = None
    ) -> StoredConversation:
        now = now_iso()
        conversation = StoredConversation(
            id=new_conversation_id(),
            user_id=user_id,
            title=title or "Nouvelle conversation",
            title_is_custom=False,
            context={},
            created_at=now,
            updated_at=now,
        )
        await self._table(_CONVERSATIONS_TABLE).create_entity(
            {
                "PartitionKey": user_id,
                "RowKey": conversation.id,
                "title": conversation.title,
                "title_is_custom": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        return conversation

    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> StoredConversation | None:
        existing = await self.get_conversation(user_id, conversation_id)
        if existing is None:
            return None
        await self._upsert_conversation(
            existing, title=title, title_is_custom=True, updated_at=now_iso()
        )
        return await self.get_conversation(user_id, conversation_id)

    async def delete_conversation(
        self, user_id: str, conversation_id: str
    ) -> bool:
        if await self.get_conversation(user_id, conversation_id) is None:
            return False
        await self._delete_message_partition(conversation_id)
        await self._table(_CONVERSATIONS_TABLE).delete_entity(
            user_id, conversation_id
        )
        return True

    async def delete_all_conversations(self, user_id: str) -> int:
        conversations = await self.list_conversations(user_id)
        for conversation in conversations:
            await self._delete_message_partition(conversation.id)
            await self._table(_CONVERSATIONS_TABLE).delete_entity(
                user_id, conversation.id
            )
        return len(conversations)

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
        now = now_iso()
        existing = await self.get_conversation(user_id, conversation_id)
        if existing is None:
            conversation = StoredConversation(
                id=conversation_id,
                user_id=user_id,
                title=derive_title(user_message),
                title_is_custom=False,
                context=context or {},
                created_at=now,
                updated_at=now,
            )
            await self._upsert_conversation(
                conversation,
                title=conversation.title,
                title_is_custom=False,
                updated_at=now,
                created_at=now,
                context=context,
            )
        else:
            title = existing.title
            if not existing.title_is_custom and not await self._has_messages(
                conversation_id
            ):
                title = derive_title(user_message)
            await self._upsert_conversation(
                existing,
                title=title,
                title_is_custom=existing.title_is_custom,
                updated_at=now,
                context=context,
            )

        messages_client = self._table(_MESSAGES_TABLE)
        user_entity: dict[str, object] = {
            "PartitionKey": conversation_id,
            "RowKey": _message_row_key(),
            "role": "user",
            "content": user_message,
            "created_at": now,
        }
        assistant_entity: dict[str, object] = {
            "PartitionKey": conversation_id,
            "RowKey": _message_row_key(),
            "role": "assistant",
            "content": assistant_message,
            "created_at": now,
        }
        _pack_json(assistant_entity, "ui_json", assistant_ui)
        await messages_client.create_entity(user_entity)
        await messages_client.create_entity(assistant_entity)

        stored = await self.get_conversation(user_id, conversation_id)
        assert stored is not None
        return stored

    async def save_context(
        self, user_id: str, conversation_id: str, context: dict[str, object]
    ) -> None:
        existing = await self.get_conversation(user_id, conversation_id)
        if existing is None:
            return
        await self._upsert_conversation(
            existing,
            title=existing.title,
            title_is_custom=existing.title_is_custom,
            updated_at=existing.updated_at,
            context=context,
        )

    async def _upsert_conversation(
        self,
        conversation: StoredConversation,
        *,
        title: str,
        title_is_custom: bool,
        updated_at: str,
        created_at: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        entity: dict[str, object] = {
            "PartitionKey": conversation.user_id,
            "RowKey": conversation.id,
            "title": title,
            "title_is_custom": title_is_custom,
            "created_at": created_at or conversation.created_at,
            "updated_at": updated_at,
        }
        _pack_json(
            entity,
            "context_json",
            context if context is not None else conversation.context,
        )
        # mode=replace drops stale context chunks from prior writes.
        await self._table(_CONVERSATIONS_TABLE).upsert_entity(
            entity, mode="replace"
        )

    async def _has_messages(self, conversation_id: str) -> bool:
        client = self._table(_MESSAGES_TABLE)
        entities = client.query_entities(
            "PartitionKey eq @conv",
            parameters={"conv": conversation_id},
            select=["RowKey"],
            results_per_page=1,
        )
        async for _ in entities:
            return True
        return False

    async def _delete_message_partition(self, conversation_id: str) -> None:
        client = self._table(_MESSAGES_TABLE)
        entities = client.query_entities(
            "PartitionKey eq @conv",
            parameters={"conv": conversation_id},
            select=["PartitionKey", "RowKey"],
        )
        batch: list[tuple[str, dict[str, object]]] = []
        async for entity in entities:
            batch.append(
                (
                    "delete",
                    {
                        "PartitionKey": entity["PartitionKey"],
                        "RowKey": entity["RowKey"],
                    },
                )
            )
            if len(batch) == 100:  # transaction cap per partition
                await self._submit(client, batch)
                batch = []
        if batch:
            await self._submit(client, batch)

    @staticmethod
    async def _submit(client, batch) -> None:
        try:
            await client.submit_transaction(batch)
        except HttpResponseError:
            logger.exception("conversation_store.azure.batch_delete_failed")
            raise
