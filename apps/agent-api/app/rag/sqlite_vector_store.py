"""SQLite backend for the CV vector index.

Used for local development, tests, and single-replica deployments. The
vector is stored as a BLOB (little-endian float32) rather than JSON:
25k candidates x 512 dims is ~53 MB as float32 versus ~250 MB as JSON
text.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import aiosqlite

from app.rag.models import IndexedCandidate, decode_vector, encode_vector

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cv_index (
    candidate_id TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    doc_hash TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    dims INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cv_index_hash ON cv_index(doc_hash);
"""


def _loads(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class SqliteVectorStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("rag_store.sqlite.ready", extra={"path": self._db_path})

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _require(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteVectorStore.initialize() was not awaited")
        return self._db

    async def upsert_many(self, entries: list[IndexedCandidate]) -> int:
        if not entries:
            return 0
        db = self._require()
        rows = []
        for raw in entries:
            entry = raw.with_defaults()
            rows.append(
                (
                    entry.candidate_id,
                    base64.b64decode(encode_vector(entry.vector)),
                    json.dumps(entry.summary, ensure_ascii=False),
                    entry.doc_hash,
                    entry.model,
                    entry.dims,
                    entry.indexed_at,
                )
            )
        await db.executemany(
            "INSERT INTO cv_index "
            "(candidate_id, vector, summary_json, doc_hash, model, dims, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET "
            "vector=excluded.vector, summary_json=excluded.summary_json, "
            "doc_hash=excluded.doc_hash, model=excluded.model, "
            "dims=excluded.dims, indexed_at=excluded.indexed_at",
            rows,
        )
        await db.commit()
        return len(rows)

    async def load_all(self) -> list[IndexedCandidate]:
        db = self._require()
        async with db.execute(
            "SELECT candidate_id, vector, summary_json, doc_hash, model, dims, "
            "indexed_at FROM cv_index"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            IndexedCandidate(
                candidate_id=row["candidate_id"],
                vector=decode_vector(base64.b64encode(row["vector"]).decode("ascii")),
                summary=_loads(row["summary_json"]),
                doc_hash=row["doc_hash"],
                model=row["model"],
                dims=int(row["dims"] or 0),
                indexed_at=row["indexed_at"],
            )
            for row in rows
        ]

    async def get_hashes(self) -> dict[str, str]:
        db = self._require()
        async with db.execute(
            "SELECT candidate_id, doc_hash FROM cv_index"
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["candidate_id"]: row["doc_hash"] for row in rows}

    async def count(self) -> int:
        db = self._require()
        async with db.execute("SELECT COUNT(*) AS n FROM cv_index") as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def delete(self, candidate_id: str) -> bool:
        db = self._require()
        cursor = await db.execute(
            "DELETE FROM cv_index WHERE candidate_id = ?", (candidate_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
