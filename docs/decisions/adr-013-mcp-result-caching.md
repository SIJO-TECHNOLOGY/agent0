# ADR-013: TTL caching of semi-stable MCP results in the Agent API

## Status

Accepted (2026-08-06)

## Context

Every full search issues on the order of 55–60 MCP calls to the
BoondManager server:

- `getDictionary` (quasi-static reference data) is fetched up to three
  times **per request** — once for filter resolution in
  `_resolve_search_filters`, once in the search ladder, once in
  `enrich_candidates` for label resolution. The MCP server only caches
  two dictionary sections (availability, experience) internally.
- Candidate enrichment performs up to 4 sequential calls per candidate
  for up to 12 candidates. Two of those payloads are semi-stable: the
  CV (`getCandidateCV`, which triggers a PDF download + PDFBox text
  extraction server-side on every call) and the technical document
  (`getCandidateTechnicalDocument`). A candidate appearing in ten
  searches has their CV downloaded and re-extracted ten times.

Nothing was cached across requests or users. This is pure latency and
load with no freshness benefit for data that changes rarely.

An alternative considered was a semantic index / RAG over CVs. That is
a different feature (semantic recall) with a much larger footprint
(vector store, ingestion pipeline, freshness strategy) and is **not**
what this ADR decides; it remains a possible future step gated on
evidence that keyword recall misses good candidates.

## Decision

Add a `CachingMcpClient` decorator (`app/mcp/caching_client.py`)
around whichever client the factory builds (mock or remote). It holds
a bounded in-process TTL cache:

| Cached | TTL (default) | Key |
|---|---|---|
| `getDictionary` | 6 h | tool + canonical inputs |
| `getCandidateCV` | 6 h | tool + candidate id |
| `getCandidateTechnicalDocument` | 6 h | tool + candidate id |
| `discover_tools()` catalogue | 5 min | fixed |

Rules:

- **Volatile data is never cached**: `searchCandidates`,
  `getCandidateDetail`, `getCandidateAdministrative` always pass
  through. Serving a stale availability, pipeline state, or salary
  could surface an already-placed candidate.
- Only successful, **non-empty** results are stored. A CV response
  without `hasContent` is not cached, so a candidate who uploads a CV
  becomes visible on the next search, not after a TTL window.
- Errors always propagate uncached; MCP graceful-degradation behavior
  (ADR-003) is unchanged.
- Entries are deep-copied on read and write so downstream mutation
  cannot poison the cache.
- LRU eviction beyond `MCP_CACHE_MAX_ENTRIES` (default 512).
- Config via `MCP_CACHE_*` settings; `MCP_CACHE_ENABLED=false` or a
  TTL of 0 disables (whole cache / one category respectively).

The cache lives at the MCP-client boundary, so no graph node changed:
`_fetch_dictionary`'s three call sites now hit the cache after the
first call transparently.

## Consequences

- A full search drops from ~55–60 MCP calls to roughly the volatile
  set (search passes + detail + administrative), typically halving the
  call count and removing the repeated PDF extraction entirely for
  warm candidates.
- Staleness is bounded by the TTLs: a replaced CV or an edited
  technical document can be up to 6 h stale. Operators can lower the
  TTLs if that trade-off is wrong for their usage.
- The cache is per-process. Multiple replicas each warm their own
  cache, and a restart clears it. If replica count grows, a shared
  cache (Redis / Azure Table via the existing storage factory pattern)
  is the natural next step — deliberately out of scope here.
- Architecture boundary intact: MCP remains the only path to
  BoondManager data; the Agent API stores *responses of MCP calls*,
  it does not talk to BoondManager.
