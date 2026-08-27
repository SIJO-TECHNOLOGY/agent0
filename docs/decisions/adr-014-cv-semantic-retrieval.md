# ADR-014: Semantic CV retrieval (RAG) as an additive recall channel

## Status

**Merged, shipped disabled** (2026-08-26). The channel is in `main` but
`ENABLE_CV_RAG` defaults to `false`, so it contributes nothing to search
until an operator turns it on.

This is deliberately *not* "adopted": the A/B evaluation found no
measurable benefit (see [Evaluation](#evaluation)). It is merged so the
code stays on the maintained path — reviewed, covered by the test
suite, and moving with refactors — rather than rotting on a branch that
would need re-validation before it could ever be used. See
[Disposition](#disposition).

Originally recorded as Accepted (2026-08-06), before the channel had
been measured against the live base. That original reasoning is kept
below unedited, because the gap between it and the measured outcome is
the useful part of this record.

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

> **Premise 1 turned out to be false.** `searchCandidates` defaults to
> `keywordsType=resumeTd` — *resume + technical document* — so
> BoondManager already full-text searches CV content. The vocabulary
> problem is real but much narrower than stated here: it is pure
> synonymy, not unreachable text. This was discovered while evaluating
> the channel, not while designing it.

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

*Written as projections, before measurement. The first bullet is the one
the evaluation disproved.*

- ~~Recall becomes vocabulary-robust and is no longer bounded by keyword
  luck~~; the 12-candidate enrichment budget is now spent on a pool that
  includes semantic matches. **Measured: the displayed page did not
  change on 7 of 8 queries.**
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

## Evaluation

The channel was measured before adoption, against the live MCP server
and real BoondManager data.

### Indexing the whole base

| | |
| --- | --- |
| Candidates indexed | **24 313** |
| Not indexable (no CV, no technical document) | 1 520 (~6%) |
| Failures | **0** |
| Duration | ~3 h at 8 concurrent |
| Index size | 107 MB on disk, ~50 MB resident |

The bulk script proved resumable and incremental in practice: the run
was interrupted and restarted, and content-hash gating skipped the
already-indexed candidates without re-embedding them.

### A/B measurement

Two instances of the same build, differing only by `ENABLE_CV_RAG`,
over 8 queries spanning keyword-friendly ("développeur Java Spring
senior"), business-language ("quelqu'un qui a fait de la migration vers
le cloud"), and deliberately-poor-coverage ("développeur mobile iOS
Swift") cases:

| Measure | Result |
| --- | --- |
| Queries where the displayed page was **identical** | **7 / 8** |
| Profiles added across all queries | 1 |
| Profiles evicted across all queries | 1 |
| Mean latency | 45 s with, 44 s without |

The single exchange was a wash on inspection: the evicted profile listed
`Swift` among finance/Drupal skills; the added one carried `Android`,
`Android Studio`, `App Store`. The same query produced 0 exchanges on an
earlier run, placing that lone data point inside the LLM planner's
run-to-run variance.

An earlier round with a partial index (~300 candidates) and a
permissive floor (`min_score=0.30`, `top_k=30`) *did* visibly dilute
results — weak hits competed for the bounded enrichment budget. That
motivated the tightening to `0.45` / `10`, after measuring the live
score distribution (clearly related ~0.5+, barely related ~0.4). The
7/8 result above is with the tightened defaults and the full index.

### What the design got right

The additive-only guarantee held under test. On the query where the
index had only noise to offer, both result lists were **identical**:
vector hits entered with score 0, failed to earn evidence, and were
dropped before display. The channel could not degrade results even when
its own suggestions were poor.

### Why the benefit did not materialise

Because premise 1 was wrong. With `keywordsType=resumeTd`, BoondManager
already searches CV text; combined with the 5-pass relaxation ladder and
evidence scoring, the existing path already reaches the profiles this
channel was built to surface. What remained was pure synonymy, and the
measurement shows the existing machinery covers enough of it that the
displayed page does not change.

## Disposition

**Merge, ship disabled.** `ENABLE_CV_RAG=false` is the default, so the
channel is inert until switched on: no index load, no query embedding,
no change to any result.

The evaluation argues against *enabling* it, not against *keeping* it.
Merging costs little and buys two things a dormant branch cannot: the
code stays reviewed and covered by the test suite, and it keeps moving
with refactors instead of drifting until it needs full re-validation.

What is paid unconditionally, even while disabled:

- **numpy** becomes a runtime dependency (~15 MB, imported at startup
  through `app.rag`). Making it a lazy or optional import is the obvious
  follow-up if that ever matters.
- Nothing else. No index is loaded, no embedding call is made, and the
  vector channel is never consulted.

What is needed before enabling it in production (none of it done):

1. Populate the index — `scripts/index_candidates.py`, ~3 h for the
   full base at 8 concurrent, hours of MCP traffic.
2. An Azure Table store plus the `Storage Table Data Contributor` role,
   and the `RAG_*` variables on `agent0-api`. See
   `infra/azure/README.md`.
3. Watch cold-start: the index loads fully into memory at startup.
   `agent0-api` runs `minReplicas: 1` today, so this is bearable — it
   would not be under scale-to-zero.

The trigger for actually turning it on should stay concrete rather than
speculative: **a real candidate, known to be in BoondManager, that
agent0 does not return.** One such case carries more weight than the
whole synthetic benchmark, and would also show which part of recall
failed.

Anyone reconsidering semantic retrieval here should start from the
`resumeTd` finding rather than re-deriving it: the question is not
"can we read CV text" — we already do — but "which specific synonym
gaps survive the ladder".
