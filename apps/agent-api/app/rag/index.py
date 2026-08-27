"""In-memory vector index over the stored CV embeddings (ADR-014).

Why a brute-force matrix product rather than an ANN index: with ~26k
candidates at 512 dims, a single float32 matrix is ~53 MB and one
query is a (26k x 512) @ (512,) product — tens of milliseconds. An
approximate index (HNSW/IVF) would add a dependency, a build step, and
recall loss to save time we are not spending. Revisit past ~500k
vectors.

Vectors are stored L2-normalised (see ``rag.models.normalise``), so the
dot product *is* the cosine similarity — no per-query renormalisation.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from app.rag.models import IndexedCandidate, VectorHit

if TYPE_CHECKING:  # pragma: no cover
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)


class VectorIndex:
    """Immutable-by-swap in-memory index.

    ``rebuild`` and ``upsert`` replace the matrix under a lock rather
    than mutating it in place, so a concurrent ``search`` always reads a
    complete, self-consistent snapshot without holding the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._summaries: list[dict[str, object]] = []
        self._matrix: NDArray[np.float32] = np.zeros((0, 0), dtype=np.float32)
        self._dims = 0

    @property
    def size(self) -> int:
        return len(self._ids)

    @property
    def dims(self) -> int:
        return self._dims

    def indexed_ids(self) -> set[str]:
        return set(self._ids)

    def rebuild(self, entries: list[IndexedCandidate]) -> None:
        """Replace the whole index from stored entries.

        Entries whose vector length disagrees with the majority are
        dropped: a dimension change (a re-configured model) must not
        crash the product — the stale ones simply stop matching until
        they are re-indexed.
        """
        usable = [e for e in entries if e.vector]
        if not usable:
            with self._lock:
                self._ids, self._summaries = [], []
                self._matrix = np.zeros((0, 0), dtype=np.float32)
                self._dims = 0
            return

        dims = _majority_dims(usable)
        kept = [e for e in usable if len(e.vector) == dims]
        dropped = len(usable) - len(kept)
        if dropped:
            logger.warning(
                "rag.index.dropped_mismatched_dims",
                extra={"dropped": dropped, "dims": dims},
            )

        matrix = np.asarray([e.vector for e in kept], dtype=np.float32)
        with self._lock:
            self._ids = [e.candidate_id for e in kept]
            self._summaries = [e.summary for e in kept]
            self._matrix = matrix
            self._dims = dims
        logger.info(
            "rag.index.rebuilt", extra={"size": len(kept), "dims": dims}
        )

    def upsert(self, entries: list[IndexedCandidate]) -> None:
        """Add or replace entries without a full reload from the store."""
        entries = [e for e in entries if e.vector and len(e.vector) == (self._dims or len(e.vector))]
        if not entries:
            return
        with self._lock:
            position = {cid: i for i, cid in enumerate(self._ids)}
            ids = list(self._ids)
            summaries = list(self._summaries)
            rows = [self._matrix] if self._matrix.size else []
            existing_rows = self._matrix.copy() if self._matrix.size else None

            appended: list[list[float]] = []
            for entry in entries:
                index = position.get(entry.candidate_id)
                if index is not None and existing_rows is not None:
                    existing_rows[index] = np.asarray(entry.vector, dtype=np.float32)
                    summaries[index] = entry.summary
                else:
                    position[entry.candidate_id] = len(ids)
                    ids.append(entry.candidate_id)
                    summaries.append(entry.summary)
                    appended.append(entry.vector)

            rows = []
            if existing_rows is not None:
                rows.append(existing_rows)
            if appended:
                rows.append(np.asarray(appended, dtype=np.float32))
            matrix = np.vstack(rows) if rows else np.zeros((0, 0), dtype=np.float32)

            self._ids = ids
            self._summaries = summaries
            self._matrix = matrix
            self._dims = matrix.shape[1] if matrix.size else self._dims

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 50,
        min_score: float = 0.0,
        exclude: set[str] | None = None,
    ) -> list[VectorHit]:
        """Return the ``top_k`` most similar candidates, best first.

        ``exclude`` drops candidates already found by another recall
        channel, so the caller gets only what the vector index *adds*.
        """
        ids, summaries, matrix = self._ids, self._summaries, self._matrix
        if not ids or matrix.size == 0 or not query_vector:
            return []
        if len(query_vector) != matrix.shape[1]:
            logger.warning(
                "rag.index.query_dims_mismatch",
                extra={"query": len(query_vector), "index": matrix.shape[1]},
            )
            return []

        query = np.asarray(query_vector, dtype=np.float32)
        scores = matrix @ query  # cosine: both sides are L2-normalised

        # Take a margin over top_k so post-filtering by `exclude` still
        # has enough left to return top_k additions.
        want = min(len(ids), top_k + len(exclude or ()))
        if want <= 0:
            return []
        top = np.argpartition(-scores, want - 1)[:want]
        top = top[np.argsort(-scores[top])]

        hits: list[VectorHit] = []
        for position in top:
            candidate_id = ids[int(position)]
            if exclude and candidate_id in exclude:
                continue
            score = float(scores[int(position)])
            if score < min_score:
                break  # sorted desc: everything after is below the floor
            hits.append(
                VectorHit(
                    candidate_id=candidate_id,
                    score=score,
                    summary=summaries[int(position)],
                )
            )
            if len(hits) >= top_k:
                break
        return hits


def _majority_dims(entries: list[IndexedCandidate]) -> int:
    counts: dict[int, int] = {}
    for entry in entries:
        counts[len(entry.vector)] = counts.get(len(entry.vector), 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]
