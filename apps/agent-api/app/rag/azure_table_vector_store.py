"""Azure Table Storage backend for the CV vector index.

Production backend, mirroring ``storage.azure_table_store``: serverless,
in-tenant, ~free at this scale, and authenticated either by connection
string or by managed identity.

Layout — table ``agent0cvindex``:

- ``PartitionKey``: a shard derived from the candidate id (see
  :func:`_shard`). Table Storage batches must stay inside one partition
  and entity listing is partition-ordered, so a single partition for 25k
  entities would serialise every write. 64 shards keep batches parallel
  while remaining few enough to scan cheaply.
- ``RowKey``: the candidate id.
- ``vector``: base64 float32, ~2.7 KB at 512 dims — comfortably inside
  the 64 KB string-property cap.
- ``summary_json_00..``: the chunked candidate summary, same packing
  scheme as the conversation store.
"""

from __future__ import annotations

import hashlib
import json
import logging

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TransactionOperation, UpdateMode
from azure.data.tables.aio import TableServiceClient

from app.rag.models import IndexedCandidate, decode_vector, encode_vector

logger = logging.getLogger(__name__)

_TABLE = "agent0cvindex"
_SHARDS = 64

# 64 KB per string property means 32 K UTF-16 code units; stay under it.
_CHUNK_CHARS = 30_000
_MAX_CHUNKS = 4  # a candidate summary is small; 120 K chars is ample
# Table Storage caps a transaction at 100 entities of one partition.
_BATCH_MAX = 100


def _shard(candidate_id: str) -> str:
    digest = hashlib.sha1(candidate_id.encode("utf-8")).digest()
    return f"{digest[0] % _SHARDS:03d}"


def _pack_json(entity: dict[str, object], prefix: str, payload: dict[str, object]) -> None:
    if not payload:
        return
    text = json.dumps(payload, ensure_ascii=False)
    chunks = [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]
    if len(chunks) > _MAX_CHUNKS:
        logger.warning(
            "rag_store.azure.summary_truncated", extra={"chunks": len(chunks)}
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


def _entity_to_indexed(entity: dict[str, object]) -> IndexedCandidate:
    return IndexedCandidate(
        candidate_id=str(entity["RowKey"]),
        vector=decode_vector(str(entity.get("vector") or "")),
        summary=_unpack_json(entity, "summary_json"),
        doc_hash=str(entity.get("doc_hash") or ""),
        model=str(entity.get("model") or ""),
        dims=int(entity.get("dims") or 0),
        indexed_at=str(entity.get("indexed_at") or ""),
    )


class AzureTableVectorStore:
    def __init__(
        self,
        *,
        connection_string: str | None = None,
        account_url: str | None = None,
    ) -> None:
        if not connection_string and not account_url:
            raise ValueError(
                "AzureTableVectorStore needs a connection string or an account URL."
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
        try:
            await self._service.create_table(_TABLE)
        except ResourceExistsError:
            pass
        logger.info("rag_store.azure.ready", extra={"table": _TABLE})

    async def close(self) -> None:
        if self._service is not None:
            await self._service.close()
            self._service = None
        if self._credential is not None:
            await self._credential.close()
            self._credential = None

    def _table(self):
        if self._service is None:
            raise RuntimeError("AzureTableVectorStore used before initialize()")
        return self._service.get_table_client(_TABLE)

    async def upsert_many(self, entries: list[IndexedCandidate]) -> int:
        if not entries:
            return 0
        client = self._table()

        by_shard: dict[str, list[dict[str, object]]] = {}
        for raw in entries:
            entry = raw.with_defaults()
            entity: dict[str, object] = {
                "PartitionKey": _shard(entry.candidate_id),
                "RowKey": entry.candidate_id,
                "vector": encode_vector(entry.vector),
                "doc_hash": entry.doc_hash,
                "model": entry.model,
                "dims": entry.dims,
                "indexed_at": entry.indexed_at,
            }
            _pack_json(entity, "summary_json", entry.summary)
            by_shard.setdefault(str(entity["PartitionKey"]), []).append(entity)

        written = 0
        for entities in by_shard.values():
            for start in range(0, len(entities), _BATCH_MAX):
                chunk = entities[start : start + _BATCH_MAX]
                await client.submit_transaction(
                    [
                        (TransactionOperation.UPSERT, entity, {"mode": UpdateMode.REPLACE})
                        for entity in chunk
                    ]
                )
                written += len(chunk)
        return written

    async def load_all(self) -> list[IndexedCandidate]:
        client = self._table()
        return [_entity_to_indexed(entity) async for entity in client.list_entities()]

    async def get_hashes(self) -> dict[str, str]:
        client = self._table()
        entities = client.list_entities(
            select=["PartitionKey", "RowKey", "doc_hash"]
        )
        return {
            str(entity["RowKey"]): str(entity.get("doc_hash") or "")
            async for entity in entities
        }

    async def count(self) -> int:
        client = self._table()
        total = 0
        async for _ in client.list_entities(select=["PartitionKey", "RowKey"]):
            total += 1
        return total

    async def delete(self, candidate_id: str) -> bool:
        client = self._table()
        try:
            await client.delete_entity(_shard(candidate_id), candidate_id)
        except ResourceNotFoundError:
            return False
        return True
