"""Value objects for the CV vector index (ADR-014).

Vectors are stored **L2-normalised** so that cosine similarity is a plain
dot product at query time. They are serialised as little-endian float32
via ``array.array``, which is ~4x smaller than a JSON float list and
loads without a JSON parse.
"""

from __future__ import annotations

import base64
import hashlib
import sys
from array import array
from dataclasses import dataclass, field
from datetime import UTC, datetime

_FLOAT_CODE = "f"  # 4-byte float


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def content_hash(text: str) -> str:
    """Stable digest of the embedded document, to skip unchanged re-embeds."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def normalise(vector: list[float]) -> list[float]:
    """Return the L2-normalised vector (zero vector returned unchanged)."""
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0.0:
        return list(vector)
    return [value / norm for value in vector]


def encode_vector(vector: list[float]) -> str:
    """Serialise a float vector as base64 little-endian float32."""
    buffer = array(_FLOAT_CODE, vector)
    if sys.byteorder != "little":  # pragma: no cover — x86/ARM are little
        buffer.byteswap()
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def decode_vector(encoded: str) -> list[float]:
    """Inverse of :func:`encode_vector`. Returns [] on malformed input."""
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return []
    if len(raw) % 4:
        return []
    buffer = array(_FLOAT_CODE)
    buffer.frombytes(raw)
    if sys.byteorder != "little":  # pragma: no cover
        buffer.byteswap()
    return list(buffer)


@dataclass(frozen=True)
class IndexedCandidate:
    """One candidate's embedded CV document plus the summary to rebuild a card.

    ``summary`` is a ``searchCandidates``-shaped record kept alongside the
    vector so a vector-only hit (a candidate the keyword search never
    returned) can become a ``SearchResult`` without an extra MCP round
    trip. It is a snapshot: volatile fields on it are refreshed by the
    normal enrichment path before anything reaches the user.
    """

    candidate_id: str
    vector: list[float]
    summary: dict[str, object] = field(default_factory=dict)
    doc_hash: str = ""
    model: str = ""
    dims: int = 0
    indexed_at: str = ""

    def with_defaults(self) -> IndexedCandidate:
        """Fill derived fields (dims, indexed_at) when not set explicitly."""
        return IndexedCandidate(
            candidate_id=self.candidate_id,
            vector=self.vector,
            summary=self.summary,
            doc_hash=self.doc_hash,
            model=self.model,
            dims=self.dims or len(self.vector),
            indexed_at=self.indexed_at or now_iso(),
        )


@dataclass(frozen=True)
class VectorHit:
    """A single vector-search result."""

    candidate_id: str
    score: float
    summary: dict[str, object] = field(default_factory=dict)
