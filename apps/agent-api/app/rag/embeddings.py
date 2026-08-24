"""Batched OpenAI embeddings for the CV index (ADR-014).

Separate from ``services.semantic_scorer``: that one computes a small
re-ranking boost with an in-process cache, this one embeds thousands of
documents for durable storage. Both can run against the same model.

Vectors come back **L2-normalised** so the retriever's dot product is a
cosine similarity.

Dimensionality is reduced via the embedding API's ``dimensions``
parameter (Matryoshka): 512 dims keeps ~99% of the ranking quality of
the full 1536 at a third of the memory — which matters when the whole
index is held in RAM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from app.rag.models import normalise

logger = logging.getLogger(__name__)

# The embeddings endpoint accepts large arrays, but a smaller batch keeps
# one failure from wasting a big call and keeps latency observable.
_BATCH_SIZE: Final[int] = 64
_MAX_ATTEMPTS: Final[int] = 3
_RETRY_BASE_DELAY: Final[float] = 1.0


class EmbeddingError(RuntimeError):
    """Raised when a batch could not be embedded after retries."""


class EmbeddingClient:
    """Async embedding client with batching and bounded retries."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "text-embedding-3-small",
        dims: int = 512,
        batch_size: int = _BATCH_SIZE,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover — dependency present
            raise RuntimeError(
                "openai package is required for CV RAG embeddings"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dims = dims
        self._batch_size = max(1, batch_size)

    @property
    def model(self) -> str:
        return self._model

    @property
    def dims(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` in order, returning L2-normalised vectors.

        Empty / whitespace-only inputs get a zero vector without an API
        call — the retriever scores them 0 and they never surface.
        Raises :class:`EmbeddingError` if a batch fails after retries, so
        the indexer can record the failure instead of silently storing
        zero vectors that would look like "indexed but never matches".
        """
        if not texts:
            return []

        out: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            if text and text.strip():
                pending.append((index, text))
            else:
                out[index] = [0.0] * self._dims

        for start in range(0, len(pending), self._batch_size):
            chunk = pending[start : start + self._batch_size]
            vectors = await self._embed_batch([text for _, text in chunk])
            for (index, _), vector in zip(chunk, vectors):
                out[index] = normalise(vector)

        return [vector or [0.0] * self._dims for vector in out]

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0] if vectors else [0.0] * self._dims

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                    dimensions=self._dims,
                )
            except Exception as exc:  # noqa: BLE001 — provider-agnostic retry
                last_error = exc
                if attempt == _MAX_ATTEMPTS:
                    break
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "rag.embed_retry",
                    extra={"attempt": attempt, "delay_s": delay, "size": len(texts)},
                )
                await asyncio.sleep(delay)
                continue
            return [item.embedding for item in response.data]

        raise EmbeddingError(
            f"embedding batch of {len(texts)} failed after {_MAX_ATTEMPTS} "
            f"attempts: {last_error}"
        ) from last_error
