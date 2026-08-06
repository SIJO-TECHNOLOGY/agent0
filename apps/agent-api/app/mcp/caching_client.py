"""TTL-caching decorator around an MCP client.

Every search re-fetches data that changes rarely: the BoondManager
reference dictionary is called up to three times per request, and each
enriched candidate re-downloads its CV text and technical document on
every search where it appears. This wrapper caches exactly those
semi-stable results in process memory, bounded by TTL and entry count.

Volatile candidate data (search results, detail, administrative /
salary) is deliberately NEVER cached: serving a stale availability or
pipeline state could surface an already-placed candidate.

See docs/decisions/adr-013-mcp-result-caching.md for the rationale and
the cacheability rules per tool.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from collections import OrderedDict
from typing import Callable, Final

from app.mcp.client import McpClient
from app.models.tools import McpTool

logger = logging.getLogger(__name__)

# Tool names mirror the constants in app.graph.nodes; they are duplicated
# here because the MCP layer must not import from the graph layer.
DICTIONARY_TOOL: Final[str] = "getDictionary"
TECHNICAL_DOCUMENT_TOOL: Final[str] = "getCandidateTechnicalDocument"
RESUME_TOOL: Final[str] = "getCandidateCV"

_TOOLS_CATALOGUE_KEY: Final[str] = "__discover_tools__"


def _records_cacheable(tool: str, records: list[dict[str, object]]) -> bool:
    """Whether a successful result is worth caching.

    Empty results are never cached so a candidate who uploads a CV (or a
    dictionary that failed to load) is re-checked on the next search
    instead of being masked for a full TTL window.
    """
    if not records:
        return False
    if tool == RESUME_TOOL:
        first = records[0]
        return isinstance(first, dict) and bool(first.get("hasContent"))
    return True


class CachingMcpClient(McpClient):
    """Decorator adding a bounded TTL cache to any `McpClient`.

    Cache policy:
    - `getDictionary` -> `dictionary_ttl_seconds` (quasi-static reference data)
    - `getCandidateTechnicalDocument`, `getCandidateCV` ->
      `candidate_doc_ttl_seconds` (semi-stable, keyed by candidate id)
    - `discover_tools()` -> `tools_ttl_seconds` (tool catalogue)
    - every other tool -> pass-through, never cached

    A TTL of 0 disables caching for that category. Only successful,
    non-empty results are stored; errors always propagate uncached.
    Entries are copied on read and write so downstream mutation of a
    result can never poison the cache. Concurrent misses on the same key
    may fetch twice (no single-flight lock) — harmless, last write wins.
    """

    def __init__(
        self,
        inner: McpClient,
        *,
        dictionary_ttl_seconds: float = 21600.0,
        candidate_doc_ttl_seconds: float = 21600.0,
        tools_ttl_seconds: float = 300.0,
        max_entries: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl_by_tool: dict[str, float] = {
            DICTIONARY_TOOL: dictionary_ttl_seconds,
            TECHNICAL_DOCUMENT_TOOL: candidate_doc_ttl_seconds,
            RESUME_TOOL: candidate_doc_ttl_seconds,
        }
        self._tools_ttl = tools_ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        # key -> (expires_at, value); OrderedDict gives LRU eviction.
        self._entries: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.stats: dict[str, int] = {"hits": 0, "misses": 0, "evictions": 0}

    @property
    def inner(self) -> McpClient:
        return self._inner

    # -- McpClient interface -------------------------------------------------

    async def discover_tools(self) -> list[McpTool]:
        cached = self._get(_TOOLS_CATALOGUE_KEY)
        if cached is not None:
            return [tool.model_copy(deep=True) for tool in cached]

        tools = await self._inner.discover_tools()
        if tools and self._tools_ttl > 0:
            self._put(
                _TOOLS_CATALOGUE_KEY,
                [tool.model_copy(deep=True) for tool in tools],
                self._tools_ttl,
            )
        return tools

    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        ttl = self._ttl_by_tool.get(tool, 0.0)
        if ttl <= 0:
            return await self._inner.call_tool(tool, inputs)

        key = self._cache_key(tool, inputs)
        cached = self._get(key)
        if cached is not None:
            return copy.deepcopy(cached)

        records = await self._inner.call_tool(tool, inputs)
        if _records_cacheable(tool, records):
            self._put(key, copy.deepcopy(records), ttl)
        return records

    # -- lifecycle passthrough (lifespan uses getattr, mock has neither) -----

    async def connect(self) -> None:
        connect = getattr(self._inner, "connect", None)
        if callable(connect):
            await connect()

    async def aclose(self) -> None:
        self.clear()
        for attr in ("aclose", "close"):
            method = getattr(self._inner, attr, None)
            if callable(method):
                result = method()
                if hasattr(result, "__await__"):
                    await result
                return

    # -- cache internals -----------------------------------------------------

    def clear(self) -> None:
        self._entries.clear()

    @staticmethod
    def _cache_key(tool: str, inputs: dict[str, object]) -> str:
        return f"{tool}:{json.dumps(inputs, sort_keys=True, default=str)}"

    def _get(self, key: str) -> object | None:
        entry = self._entries.get(key)
        if entry is None:
            self.stats["misses"] += 1
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            self.stats["misses"] += 1
            return None
        self._entries.move_to_end(key)
        self.stats["hits"] += 1
        logger.debug("mcp_cache.hit", extra={"key": key})
        return value

    def _put(self, key: str, value: object, ttl: float) -> None:
        self._entries[key] = (self._clock() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            evicted_key, _ = self._entries.popitem(last=False)
            self.stats["evictions"] += 1
            logger.debug("mcp_cache.evicted", extra={"key": evicted_key})
