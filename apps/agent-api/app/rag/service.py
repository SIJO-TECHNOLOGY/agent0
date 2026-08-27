"""RagService: the single entry point the graph uses for CV retrieval.

Ties the four pieces together — embeddings, durable store, in-memory
index, indexer — and owns the two behaviours the search flow needs:

- :meth:`search` — the vector recall channel;
- :meth:`catch_up` — index candidates seen during a search that are not
  in the index yet, so the index fills in as the tool gets used.

Every method is failure-tolerant by design: RAG is an *additive* recall
channel (ADR-014), so any error degrades to "no extra candidates", never
to a failed search.
"""

from __future__ import annotations

import asyncio
import logging

from app.rag.document import build_query_document
from app.rag.embeddings import EmbeddingClient
from app.rag.index import VectorIndex
from app.rag.indexer import CandidateIndexer, CandidatePayload
from app.rag.models import VectorHit
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)


class RagService:
    def __init__(
        self,
        *,
        store: VectorStore,
        embeddings: EmbeddingClient,
        indexer: CandidateIndexer,
        index: VectorIndex | None = None,
        top_k: int = 30,
        min_score: float = 0.30,
        catch_up_enabled: bool = True,
    ) -> None:
        self._store = store
        self._embeddings = embeddings
        self._indexer = indexer
        self._index = index or VectorIndex()
        self._top_k = top_k
        self._min_score = min_score
        self._catch_up_enabled = catch_up_enabled
        self._loaded = False
        self._load_lock = asyncio.Lock()

    @property
    def index(self) -> VectorIndex:
        return self._index

    @property
    def size(self) -> int:
        return self._index.size

    async def startup(self) -> int:
        """Open the store and load the index into memory. Returns its size.

        Store configuration errors propagate (an operator who enabled RAG
        must not silently get a keyword-only search), but an *empty*
        index is a normal state: the vector channel just contributes
        nothing until the indexing script has run.
        """
        await self._store.initialize()
        return await self.load()

    async def close(self) -> None:
        try:
            await self._store.close()
        except Exception:  # noqa: BLE001 — shutdown best-effort
            logger.exception("rag.close_failed")

    async def load(self) -> int:
        """Load the durable index into memory. Idempotent.

        Kept separate from ``startup`` so tests (and a future refresh
        endpoint) can reload without reopening the store.
        """
        async with self._load_lock:
            if self._loaded:
                return self._index.size
            try:
                entries = await self._store.load_all()
            except Exception:  # noqa: BLE001 — degraded, not fatal
                logger.exception("rag.load_failed")
                self._loaded = True  # don't hammer a broken store per request
                return 0
            self._index.rebuild(entries)
            self._loaded = True
            logger.info("rag.loaded", extra={"size": self._index.size})
            return self._index.size

    async def search(
        self,
        *,
        entities: list[str] | None = None,
        objective: str = "",
        role: str | None = None,
        exclude: set[str] | None = None,
        top_k: int | None = None,
    ) -> list[VectorHit]:
        """Vector recall for one query. Returns [] on any failure."""
        if self._index.size == 0:
            return []
        query = build_query_document(
            entities=entities, objective=objective, role=role
        )
        if not query:
            return []
        try:
            vector = await self._embeddings.embed_one(query)
        except Exception:  # noqa: BLE001 — additive channel
            logger.exception("rag.query_embed_failed")
            return []
        hits = self._index.search(
            vector,
            top_k=top_k or self._top_k,
            min_score=self._min_score,
            exclude=exclude,
        )
        logger.info(
            "rag.search",
            extra={
                "index_size": self._index.size,
                "hits": len(hits),
                "top_score": round(hits[0].score, 4) if hits else None,
            },
        )
        return hits

    async def catch_up(self, payloads: list[CandidatePayload]) -> int:
        """Index candidates seen in this search that the index lacks.

        Takes the CV / technical-document payloads enrichment already
        downloaded, so catching up costs embeddings only — no extra MCP
        calls. Returns how many candidates were added.
        """
        if not self._catch_up_enabled or not payloads:
            return 0
        known = self._index.indexed_ids()
        missing = [
            payload
            for payload in payloads
            if payload.candidate_id and payload.candidate_id not in known
        ]
        if not missing:
            return 0
        try:
            entries, report = await self._indexer.index_payloads(missing)
        except Exception:  # noqa: BLE001 — background enrichment of the index
            logger.exception("rag.catch_up_failed")
            return 0
        if entries:
            self._index.upsert(entries)
        logger.info("rag.catch_up", extra=report.as_dict())
        return len(entries)
