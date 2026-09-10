# ADR-017: Multi-source candidate search (BoondManager + LinkedIn/Web)

## Status

Accepted (2026-09-10)

## Context

Agent0 searched BoondManager only. SIJO wanted to also discover external
candidates from public LinkedIn pages, let recruiters choose the source(s), and
merge/rank both together — while keeping the strict rule that `mcp-boondmanager`
stays BoondManager-only.

Constraints:

- **Deterministic source routing.** The user's source choice must be honoured
  exactly; the LLM planner must never flip it.
- **Public web only.** No LinkedIn login/cookies/Recruiter, no browser
  automation/scraping, no constructing profile URLs from names.
- **No invented candidates.** A model must never fabricate a profile.
- **SIJO qualification.** Prefer consultants; strongly value at least one client
  mission >= a configurable threshold (default 24 months).
- **Employment != mission.** A long tenure at one employer is NOT proof of one
  long *client* mission.
- **UNKNOWN != NO.** Sparse public data must not be scored like a confirmed
  absence.

## Decision

### Source selection
`CandidateSource` enum (`boond`, `linkedin`) + one resolution rule
(`resolve_candidate_sources`): a selection is honoured as-is; "no selection"
resolves to BOTH when external search is enabled, else Boond only; a disabled
source is dropped. Resolved once in `SearchService`, stored in
`GraphState.sources`. Boond execution nodes short-circuit when `boond` is not in
the set; the `search_external` node no-ops when `linkedin` is not. The LLM plan
is used only to interpret the query, never to route.

### External discovery (agent-api only; never mcp-boondmanager)
Lives in `app/candidate_sources/`. LinkedIn discovery uses the OpenAI Responses
API in **two grounded steps** (behind an injectable, mockable backend):

1. `responses.create` + the built-in `web_search` tool → the model actually
   searches; its `url_citation` annotations are the **real** pages retrieved.
2. `responses.parse` (no tool) structures ONLY the cited profiles.

Structured output is never combined with `web_search`: that suppresses
citations and lets the model fabricate. **Grounding is mandatory** — a profile
is accepted only if its canonical `/in/` URL is among the cited sources; no
citation => rejected (this is what stops hallucinated "Jane Doe" profiles).

A bounded, de-duplicated query **ladder** (consulting/title/skill/company/
geography passes) runs its passes **concurrently** (`asyncio.gather`) to keep
latency low; a missing name is derived from the `/in/` slug, and a profile with
neither a name nor a title is dropped. Results are canonicalised (company/jobs/
posts/pulse rejected) and deduped by canonical identifier.

### Models
`EXTERNAL_SEARCH_MODEL` (default `gpt-4o`) must ground `web_search` well —
gpt-4o / gpt-5 / gpt-5.4 do; gpt-4o-mini fabricates and its ungrounded output is
rejected. `EXTERNAL_SEARCH_STRUCTURE_MODEL` (default `gpt-4o-mini`) runs the
tool-free structuring step fast. The API key falls back to `OPENAI_API_KEY`,
then to `LLM_API_KEY` when the LLM provider is OpenAI.

### SIJO qualification
`qualification` classifies the consulting profile and `mission_analysis` the
long-mission evidence, both tri-state `confirmed | probable | unknown | no`.
`analyze_long_mission` returns `confirmed` only for an explicit named client
mission >= threshold; a long tenure with no named client is at most `probable`
(and only for a clearly-consultant profile), otherwise `unknown` — never
`confirmed`.

### France / francophone rule
The real minimum bar: the candidate **speaks French AND has had an experience in
France** (nationality/current country irrelevant). Discovery captures languages
and per-experience locations. A clearly-foreign profile that evidences **neither**
is **excluded** (`CANDIDATE_REQUIRE_FRENCH_OR_FRANCE_EXPERIENCE`, default true);
an unknown location is never excluded. Île-de-France is preferred at ranking,
and `EXTERNAL_DEFAULT_LOCATION` targets France/IDF when the query names no place.

### Ranking & merge
External candidates are scored from a neutral prior with positive nudges
(matched skills, confirmed/probable consulting and long mission, French,
France-experience, region); UNKNOWN is neutral, only confirmed-NO subtracts.
They rank in the same unified, capped bucket as Boond candidates (the Boond
evidence scorer is unchanged). Same-person cards are merged only on strong
evidence — shared canonical LinkedIn URL or Boond id — never on name alone.

### Failure isolation & persistence
A LinkedIn failure surfaces a non-fatal warning and never destroys Boond results
(and vice-versa). External candidates are ephemeral (short-TTL cache), never
auto-imported into BoondManager. The Boond-style "could not verify criteria"
message is suppressed for LinkedIn-only results (public profiles have no
technical document to verify against).

## Consequences

- LinkedIn discovery reflects only public, web-indexed information; it is not
  LinkedIn Recruiter and cannot read private/authenticated data. Public details
  may be incomplete, so a long mission is only `confirmed` with enough public
  evidence; sparse or niche queries legitimately return few/no results.
- The frontend exposes a source selector (in the Filters popover) and per-card
  source badges + SIJO qualification chips; the backend remains the authority on
  availability and routing.

## New configuration

`EXTERNAL_SEARCH_ENABLED`, `EXTERNAL_SEARCH_PROVIDER`, `EXTERNAL_SEARCH_MODEL`,
`EXTERNAL_SEARCH_STRUCTURE_MODEL`, `EXTERNAL_SEARCH_MAX_QUERIES`,
`EXTERNAL_SEARCH_MAX_RESULTS`, `EXTERNAL_SEARCH_LINKEDIN_ONLY`,
`EXTERNAL_SEARCH_CACHE_TTL_SECONDS`, `EXTERNAL_SEARCH_API_KEY`,
`EXTERNAL_DEFAULT_LOCATION`, `CANDIDATE_PREFER_CONSULTING_PROFILE`,
`CANDIDATE_LONG_MISSION_THRESHOLD_MONTHS`,
`CANDIDATE_REQUIRE_FRENCH_OR_FRANCE_EXPERIENCE`.
