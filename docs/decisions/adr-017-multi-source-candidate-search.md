# ADR-017: Multi-source candidate search (BoondManager + LinkedIn/Web)

## Status

Accepted (2026-09-08)

## Context

Agent0 searched BoondManager only. SIJO wanted to also discover external
candidates from public LinkedIn pages, let recruiters choose the source(s),
and merge/rank both together — while keeping the strict architectural rule
that `mcp-boondmanager` stays BoondManager-only.

Key constraints:

- **Deterministic source routing.** The user's source selection must be
  honoured exactly; the LLM planner must never flip it.
- **Public web only.** No LinkedIn login/cookies/Recruiter, no browser
  automation/scraping, no constructing profile URLs from names.
- **SIJO qualification.** Prefer consultants, and strongly value evidence of at
  least one client mission ≥ a configurable threshold (default 24 months).
- **Employment ≠ mission.** A long tenure at one employer (e.g. "Capgemini
  2018–2025") is NOT proof of one long *client* mission.
- **UNKNOWN ≠ NO.** Sparse public data must not be scored like a confirmed
  absence.

## Decision

**Source selection.** `CandidateSource` enum (`boond`, `linkedin`) and one
resolution rule (`resolve_candidate_sources`): a selection is honoured as-is;
"no selection" resolves to BOTH when external search is enabled, else Boond
only. Resolution happens once in `SearchService` and is stored in
`GraphState.sources`; graph nodes route off it. Boond execution nodes
(`execute_mcp_tools`, `execute_llm_plan`) short-circuit when `boond` is not in
the resolved set; the `search_external` node no-ops when `linkedin` is not.
The LLM plan is used only for query interpretation, never to override routing.

**External discovery lives in `agent-api`** (`app/candidate_sources/`), never in
`mcp-boondmanager`. `linkedin_web` uses the OpenAI Responses API `web_search`
tool via an injectable backend (mockable in tests). A bounded query ladder
(consulting-first, title/skills/company/geography variants, capped by
`EXTERNAL_SEARCH_MAX_QUERIES`) recovers profiles a single strict query would
miss. Results are canonicalised, validated against the search's cited source
URLs (invented URLs rejected), deduped by canonical `/in/` identifier, and
qualified.

**Qualification is separate from discovery.** `qualification` classifies the
consulting profile and `mission_analysis` classifies long-mission evidence,
both with tri-state (+negative) status `confirmed | probable | unknown | no`.
`analyze_long_mission` only returns `confirmed` for an explicit named client
mission ≥ threshold; a long tenure with no named client is at most `probable`
(and only when the profile is clearly a consultant), else `unknown` — never
`confirmed`. `no` is assigned conservatively.

**Ranking.** External candidates are scored (`candidate_sources.ranking`) from a
neutral prior with positive nudges for matched skills, confirmed/probable
consulting and long-mission evidence, seniority and location; UNKNOWN is
neutral, only confirmed-NO subtracts. They rank in the same unified,
score-sorted, capped bucket as Boond candidates (extend, not replace, the Boond
evidence scorer, which is untouched for `search`-prefixed results).

**Merge/dedup.** Same-person cards are merged only on strong deterministic
evidence — a shared canonical LinkedIn URL or an identical Boond id — never on
name alone.

**Failure isolation.** A LinkedIn failure surfaces a non-fatal warning and
never destroys Boond results (and vice-versa).

**Config.** `EXTERNAL_SEARCH_*`, `CANDIDATE_PREFER_CONSULTING_PROFILE`,
`CANDIDATE_LONG_MISSION_THRESHOLD_MONTHS`. The threshold is the single source of
truth — never hardcoded. The external API key falls back to `OPENAI_API_KEY`.

## Consequences

- LinkedIn discovery reflects only public, web-indexed information; it is not
  LinkedIn Recruiter and cannot read private/authenticated data. Public
  experience details may be incomplete, so a long mission is only `confirmed`
  when enough public evidence exists.
- External candidates are ephemeral (short-TTL cache); they are never imported
  into BoondManager automatically.
- The frontend exposes a source selector and per-card source badges + SIJO
  qualification indicators; the backend remains the authority on availability.
