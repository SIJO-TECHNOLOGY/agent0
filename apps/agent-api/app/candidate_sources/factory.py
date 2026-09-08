"""Build the external candidate source from settings, with bounded caching.

External web search is slow and costly, so identical discoveries (same
normalized query + business settings) are served from a short-TTL in-process
cache. Nothing here holds secrets beyond the API key already in settings, and
the cache never stores credentials.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.candidate_sources.models import CandidateSearchQuery
from app.candidate_sources.linkedin_web.source import (
    ExternalDiscoveryResult,
    LinkedInWebSource,
)

logger = logging.getLogger(__name__)


def _cache_key(query: CandidateSearchQuery) -> str:
    parts = [
        "|".join(sorted(s.lower() for s in query.job_titles)),
        "|".join(sorted(s.lower() for s in query.required_skills)),
        "|".join(sorted(s.lower() for s in query.optional_skills)),
        (query.location or "").lower(),
        "|".join(sorted(c.lower() for c in query.companies)),
        str(query.min_experience_years),
        str(query.prefer_consulting_profile),
        str(query.long_mission_threshold_months),
        str(query.limit),
    ]
    return "\x1f".join(parts)


@dataclass
class _Entry:
    value: ExternalDiscoveryResult
    expires_at: float


class CachedExternalSource:
    """Wrap a source's ``discover`` with a bounded TTL cache."""

    def __init__(
        self,
        inner: LinkedInWebSource,
        *,
        ttl_seconds: float,
        max_entries: int = 128,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._max = max_entries
        self._cache: dict[str, _Entry] = {}

    async def discover(self, query: CandidateSearchQuery) -> ExternalDiscoveryResult:
        if self._ttl <= 0:
            return await self._inner.discover(query)
        key = _cache_key(query)
        now = time.monotonic()
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > now:
            return entry.value
        result = await self._inner.discover(query)
        if len(self._cache) >= self._max:
            # Evict the soonest-expiring entry (cheap approximate LRU).
            oldest = min(self._cache, key=lambda k: self._cache[k].expires_at)
            self._cache.pop(oldest, None)
        self._cache[key] = _Entry(value=result, expires_at=now + self._ttl)
        return result

    async def find_profile_for_candidate(self, *args, **kwargs):
        return await self._inner.find_profile_for_candidate(*args, **kwargs)


def build_external_source(settings) -> object | None:
    """Construct the external candidate source, or None when unavailable.

    Returns ``None`` (external discovery simply absent) when the feature is
    disabled or no API key is configured — never raises at startup.
    """
    if not getattr(settings, "external_search_enabled", False):
        return None
    if getattr(settings, "external_search_provider", "openai_web") != "openai_web":
        logger.warning(
            "external_source.unknown_provider",
            extra={"provider": settings.external_search_provider},
        )
        return None
    api_key = (
        getattr(settings, "external_search_api_key", None)
        or getattr(settings, "openai_api_key", None)
    )
    if not api_key:
        logger.warning("external_source.no_api_key")
        return None
    try:
        from app.candidate_sources.linkedin_web.openai_backend import (
            OpenAIWebSearchBackend,
        )

        backend = OpenAIWebSearchBackend(
            api_key=api_key,
            model=settings.external_search_model,
            linkedin_only=settings.external_search_linkedin_only,
            timeout_seconds=getattr(settings, "llm_timeout_seconds", 60.0),
        )
    except Exception:  # noqa: BLE001 — missing SDK/key must not break startup
        logger.warning("external_source.backend_init_failed", exc_info=True)
        return None

    source = LinkedInWebSource(
        backend,
        max_queries=settings.external_search_max_queries,
        max_results=settings.external_search_max_results,
        linkedin_only=settings.external_search_linkedin_only,
        threshold_months=settings.candidate_long_mission_threshold_months,
        prefer_consulting_profile=settings.candidate_prefer_consulting_profile,
    )
    return CachedExternalSource(
        source, ttl_seconds=settings.external_search_cache_ttl_seconds
    )
