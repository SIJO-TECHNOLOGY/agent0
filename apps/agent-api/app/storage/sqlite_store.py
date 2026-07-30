"""SQLite implementation of ConversationStore.

Used for local development and tests. aiosqlite serializes all
operations on one connection/thread, which is plenty for a
single-replica deployment and hermetic tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiosqlite

from app.storage.store import (
    StoredConversation,
    StoredMessage,
    derive_title,
    new_conversation_id,
    now_iso,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_is_custom INTEGER NOT NULL DEFAULT 0,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL
        REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ui_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);
"""


def _loads(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _conversation_from_row(row: aiosqlite.Row) -> StoredConversation:
    return StoredConversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        title_is_custom=bool(row["title_is_custom"]),
        context=_loads(row["context_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqliteConversationStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("conversation_store.sqlite.ready", extra={"path": self._db_path})

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteConversationStore used before initialize()")
        return self._db

    async def list_conversations(self, user_id: str) -> list[StoredConversation]:
        cursor = await self._conn.execute(
            "SELECT * FROM conversations WHERE user_id = ?"
            " ORDER BY updated_at DESC, id DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [_conversation_from_row(row) for row in rows]

    async def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> StoredConversation | None:
        cursor = await self._conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        row = await cursor.fetchone()
        return _conversation_from_row(row) if row else None

    async def get_messages(
        self, user_id: str, conversation_id: str
    ) -> list[StoredMessage]:
        cursor = await self._conn.execute(
            "SELECT m.role, m.content, m.ui_json, m.created_at"
            " FROM messages m JOIN conversations c ON c.id = m.conversation_id"
            " WHERE m.conversation_id = ? AND c.user_id = ?"
            " ORDER BY m.id",
            (conversation_id, user_id),
        )
        rows = await cursor.fetchall()
        return [
            StoredMessage(
                role=row["role"],
                content=row["content"],
                ui=_loads(row["ui_json"]) or None,
                created_at=row["created_at"],
            )
            for row in rows
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
        await self._conn.execute(
            "INSERT INTO conversations"
            " (id, user_id, title, title_is_custom, context_json,"
            "  created_at, updated_at)"
            " VALUES (?, ?, ?, 0, '{}', ?, ?)",
            (conversation.id, user_id, conversation.title, now, now),
        )
        await self._conn.commit()
        return conversation

    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> StoredConversation | None:
        cursor = await self._conn.execute(
            "UPDATE conversations SET title = ?, title_is_custom = 1,"
            " updated_at = ? WHERE id = ? AND user_id = ?",
            (title, now_iso(), conversation_id, user_id),
        )
        await self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get_conversation(user_id, conversation_id)

    async def delete_conversation(
        self, user_id: str, conversation_id: str
    ) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_all_conversations(self, user_id: str) -> int:
        cursor = await self._conn.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        )
        await self._conn.commit()
        return cursor.rowcount

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
            await self._conn.execute(
                "INSERT INTO conversations"
                " (id, user_id, title, title_is_custom, context_json,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, 0, ?, ?, ?)",
                (
                    conversation_id,
                    user_id,
                    derive_title(user_message),
                    json.dumps(context or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        else:
            # Auto-title a shell conversation on its first real message,
            # but never overwrite a user-chosen title.
            title = existing.title
            has_messages = await self._has_messages(conversation_id)
            if not existing.title_is_custom and not has_messages:
                title = derive_title(user_message)
            await self._conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ?,"
                " context_json = COALESCE(?, context_json)"
                " WHERE id = ? AND user_id = ?",
                (
                    title,
                    now,
                    json.dumps(context, ensure_ascii=False)
                    if context is not None
                    else None,
                    conversation_id,
                    user_id,
                ),
            )
        await self._conn.executemany(
            "INSERT INTO messages"
            " (conversation_id, role, content, ui_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (conversation_id, "user", user_message, None, now),
                (
                    conversation_id,
                    "assistant",
                    assistant_message,
                    json.dumps(assistant_ui, ensure_ascii=False)
                    if assistant_ui
                    else None,
                    now,
                ),
            ],
        )
        await self._conn.commit()
        stored = await self.get_conversation(user_id, conversation_id)
        assert stored is not None
        return stored

    async def save_context(
        self, user_id: str, conversation_id: str, context: dict[str, object]
    ) -> None:
        await self._conn.execute(
            "UPDATE conversations SET context_json = ?"
            " WHERE id = ? AND user_id = ?",
            (json.dumps(context, ensure_ascii=False), conversation_id, user_id),
        )
        await self._conn.commit()

    async def _has_messages(self, conversation_id: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        )
        return await cursor.fetchone() is not None
