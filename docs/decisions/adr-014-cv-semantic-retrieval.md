# ADR-014: Semantic CV retrieval (RAG) as an additive recall channel

## Status

Accepted (2026-08-06)

## Context

Candidate recall relies entirely on BoondManager keyword search
(`searchCandidates`), run as a relaxation ladder of up to 5 passes.
Two structural limits follow:

1. **Vocabulary sensitivity.** A candidate whose CV says "interfaces
   Next.js / TypeScript" is invisible to a "développeur React frontend"
   query unless a keyword matches literally. The ladder relaxes
   *criteria*, not *vocabulary*.
2. **The enrichment cap bounds precision, not recall.** Only the top 12
   pre-ranked summaries are enriched and finely scored; a good candidate
   whose *summary* shows weak evidence never gets their CV read.

The base is ~26k candidates (measured by paginating the live API).

## Decision

Add a semantic retrieval channel (`app/rag/`) over embedded CV
documents, **strictly additive** to keyword recall:

- **Document**: title + skills + expertise + technical document + CV
  text (administrative noise excluded), capped at ~7.5k chars —
  assembled by `rag/document.py`, mirroring the evidence haystack.
- **Embeddings**: OpenAI `text-embedding-3-small` at **512 dims**
  (Matryoshka truncation), L2-normalised at write time.
- **Storage**: `VectorStore` protocol with SQLite (dev) and Azure Table
  (production, 64 shards, float32-base64 vectors) backends — the same
  factory philosophy and credentials as the conversation store.
- **Retrieval**: a brute-force in-memory numpy matrix product. At 26k x
  512 float32 (~53 MB) a query costs tens of milliseconds; an ANN index
  (HNSW/FAISS) would add dependencies and recall loss to save time we
  do not spend. Revisit past ~500k vectors. numpy becomes a runtime
  dependency (pure Python at this scale measured ~13 s/query).
- **Wiring**: after the keyword ladder, `_augment_with_vector_recall`
  appends vector hits **absent** from the keyword results (dedup by id,
  `RAG_TOP_K` cap, `RAG_MIN_SCORE` floor). Hits enter as
  `searchCandidates`-shaped summaries with `score=0.0`, so they earn
  their rank through the same pre-ranking, enrichment, and evidence
  scoring as keyword hits. The channel changes recall only — never the
  scoring contract.
- **Ingestion**: a resumable bulk script (`scripts/index_candidates.py`)
  walks the base through MCP (~2 calls/candidate — budget hours, run
  off-peak), plus an in-search catch-up that indexes just-enriched
  candidates by reusing the payloads enrichment already downloaded
  (embeddings only, zero extra MCP calls).

### Deliberate abstentions

- **Named-person queries skip the channel** — "trouve Jean Dupont" is
  an exact lookup; embeddings would return look-alikes.
- **Queries with no skill/domain/role anchor skip it** — nothing
  meaningful to embed.
- **Volatile fields are never answered from the index.** The stored
  summary seeds the card for pre-ranking, but availability, state,
  salary, and detail come from live MCP enrichment as before. The index
  is a derived store, reconstructible at any time; MCP remains the only
  path to BoondManager data (the indexer reads through MCP tools).

### Failure semantics

Every RAG failure — store down, embedding API error, empty index —
degrades to "the channel adds nothing": the keyword search behaves
exactly as before. `ENABLE_CV_RAG=false` (the default) removes the
channel entirely. Misconfiguration with the flag *on* fails startup
(same fail-fast stance as the MCP factory).

## Consequences

- Recall becomes vocabulary-robust and is no longer bounded by keyword
  luck; the 12-candidate enrichment budget is now spent on a pool that
  includes semantic matches.
- New runtime dependency (numpy), ~53 MB RSS for the loaded index, and
  one embedding API call per search (the query embedding).
- The index ages: a candidate updated in BoondManager keeps their old
  vector until the bulk script re-runs or a search touches them
  (catch-up re-embeds on content-hash change). Acceptable for CV-shaped
  data; volatile data never comes from the index at all.
- Embedding cost is bounded and one-time-ish: ~26k documents at
  ~1k tokens each is a few dollars for the full pass; increments are
  driven by content changes only (hash-gated).
- The stored summary is a second copy of a *slice* of candidate data —
  kept deliberately minimal (card fields only) and treated as a seed
  that live enrichment overwrites.
