"""Persistence contract for the CV vector index (ADR-014).

The index is a *derived* store: every entry is reconstructible by
replaying MCP calls, so losing it costs re-indexing time, never data.
It is global rather than per-user — candidates belong to the company,
not to the recruiter who happened to search for them.
"""

from __future__ import annotations

from typing import Protocol

from app.rag.models import IndexedCandidate


class VectorStore(Protocol):
    """Async persistence contract for embedded candidate documents."""

    async def initialize(self) -> None:
        """Create schema / reach the backing service. Called at startup."""
        ...

    async def close(self) -> None:
        ...

    async def upsert_many(self, entries: list[IndexedCandidate]) -> int:
        """Insert or replace entries by candidate id; returns how many."""
        ...

    async def load_all(self) -> list[IndexedCandidate]:
        """Every indexed candidate, for building the in-memory matrix."""
        ...

    async def get_hashes(self) -> dict[str, str]:
        """``{candidate_id: doc_hash}`` — lets the indexer skip unchanged CVs.

        Deliberately separate from :meth:`load_all` so the indexing script
        can decide what to re-embed without pulling every vector.
        """
        ...

    async def count(self) -> int:
        ...

    async def delete(self, candidate_id: str) -> bool:
        """Remove one candidate from the index. False when absent."""
        ...
