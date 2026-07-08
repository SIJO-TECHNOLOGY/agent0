"""Semantic skill scoring via OpenAI text embeddings.

Computes a cosine-similarity boost between the query's skill/domain terms and
a candidate's evidence haystack.  The boost is additive on top of the
deterministic text-matching evidence score so the ranking is still
explainable: the text score drives the order, the semantic boost separates
near-ties where a synonym or paraphrase would otherwise score zero.

Usage
-----
    scorer = SemanticScorer(api_key="sk-...", model="text-embedding-3-small")
    boost = await scorer.boost(
        query_terms=["machine learning", "python"],
        candidate_text="deep learning engineer with pytorch experience",
    )
    # boost ∈ [0.0, 1.0] — multiply by semantic_boost_weight before adding

Design notes
------------
- Embeddings are cached in-process by (model, text) so repeated calls within
  the same request or across candidates for the same query terms are free.
- The query embedding is a single call for ALL terms concatenated; the
  candidate embedding is one call per candidate haystack.  Both are batched
  via the OpenAI ``/embeddings`` endpoint's ``input`` array.
- Cosine similarity is computed in pure Python (no numpy dependency) over
  the 1536-dim float vectors returned by text-embedding-3-small.
- The scorer is instantiated once at application startup (via
  ``get_semantic_scorer`` factory) and reused across requests.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Final

logger = logging.getLogger(__name__)

_CACHE_MAX: Final[int] = 4096  # max distinct texts cached per process


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticScorer:
    """Async semantic scorer backed by an OpenAI embedding model.

    Thread-safe for concurrent async usage; the embedding cache is
    instance-local so two scorers with different models don't collide.
    """

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        # Import lazily so the module loads even when openai is not installed
        # (the scorer is only instantiated when enable_semantic_scoring=true).
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for semantic scoring "
                "(pip install openai)"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._cache: dict[str, list[float]] = {}

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Fetch embeddings for a batch of texts, using the in-process cache."""
        uncached = [t for t in texts if t not in self._cache]
        if uncached:
            # Truncate each text to ~8000 chars to stay within token limits
            # for text-embedding-3-small (8192 token context).
            safe = [t[:8000] for t in uncached]
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=safe,
                )
                for text, item in zip(uncached, response.data):
                    if len(self._cache) < _CACHE_MAX:
                        self._cache[text] = item.embedding
            except Exception:
                logger.exception("semantic_scorer.embed_failed")
                # Return zero vectors on error — the boost is safely 0.0
                return [[0.0] * 1536 for _ in texts]
        return [self._cache.get(t, [0.0] * 1536) for t in texts]

    async def boost(
        self,
        query_terms: list[str],
        candidate_text: str,
    ) -> float:
        """Cosine similarity ∈ [0, 1] between query terms and candidate text.

        ``query_terms`` are the skills/domains from the interpreted intent.
        ``candidate_text`` is the candidate's evidence haystack (already
        lowercased, whitespace-collapsed).

        Returns 0.0 when either side is empty or on any API error, so the
        calling ranker can safely add it as a non-blocking boost.
        """
        if not query_terms or not candidate_text.strip():
            return 0.0
        # Represent the query as a single joined string — the embedding
        # captures the concept space of all requested terms together.
        query_str = " ".join(q.strip() for q in query_terms if q.strip())
        if not query_str:
            return 0.0

        vectors = await self._embed([query_str, candidate_text])
        query_vec, candidate_vec = vectors[0], vectors[1]
        sim = _cosine(query_vec, candidate_vec)
        # Clamp to [0, 1] — cosine can be slightly negative for unrelated texts
        return max(0.0, min(1.0, sim))


@lru_cache(maxsize=1)
def get_semantic_scorer(api_key: str, model: str) -> SemanticScorer:
    """Return a cached SemanticScorer instance (one per (api_key, model) pair)."""
    return SemanticScorer(api_key=api_key, model=model)
