# ADR-014: Candidate pipeline-state filtering (pre-query and post-query)

## Status

Accepted (2026-08-26)

## Context

BoondManager classifies candidates into pipeline states ("Vivier",
"A jouer", "Qualifié", "Import à traiter", …). Recruiters asked to
restrict searches by state — e.g. *"un dev C# de 5 ans d'expérience qui
est en Vivier"* — and to narrow an already-returned result list by
state without re-running the search.

Constraints that shaped the design:

- **Free-text state names are fragile.** A typo or a synonym silently
  matches nothing, and some state words are ordinary vocabulary: in
  "un dev qualifié", *qualifié* means "skilled", not the state
  "Qualifié". The requesting user explicitly asked for checkbox
  selection "comme dans un filtre" to avoid misinterpretation.
- **Two filtering moments** are needed: at query time (the provider
  returns only candidates in the selected states) and after the fact
  (display-only narrowing of received cards). Multiple selected states
  must be additive (union), matching BoondManager's own
  `candidateStates[]` semantics — the MCP server already exposes this
  parameter on `searchCandidates`, so no Java change was required.
- **The LLM planner must not emit dictionary ids** (prompt rule 4,
  ADR-005/ADR-007): it plans in a single pass and never sees
  `getDictionary` output, so id resolution belongs to the Agent API.
- The recall ladder (ADR-007) rebuilds `searchCandidates` inputs from
  the interpreted intent and **discards planned filters**, so a state
  filter attached only to the planned step would silently vanish.
- `state_label` existed on candidate cards but was populated only for
  the enriched slice (≤ 12 candidates), so a frontend state filter
  would have mis-bucketed most cards.
- Some states must never surface: "Ne plus contacter", "A SUPPRIMER",
  and (added on user request) "Proposition refusé".

## Decision

### One filter, three sources, resolved in one place

The intent constraint dictionary carries the state filter through two
conventional keys:

| Key | Producer | Content |
|---|---|---|
| `candidate_state_ids` | Web UI checkboxes via `filters.candidate_states` | Dictionary ids (csv) — authoritative, no resolution needed |
| `candidate_states` | LLM planner (prompt rule 13) | State names verbatim from the user's words (csv) |

A single resolver (`_resolve_candidate_state_filter` in
`app/graph/nodes.py`) turns constraints into a `candidateStates` input:

- UI-selected ids pass through as integers.
- LLM-declared labels are matched against `setting.state.candidate`
  accent- and case-insensitively (`resolve_candidate_state_ids`);
  **ids are never invented** — unmatched labels produce a
  `state_filter_unmapped` warning surfaced in the user message.
- Backstop: when no constraint is present, the raw query is scanned
  conservatively (`detect_candidate_state_labels`): multi-word labels
  ("A jouer") match on word boundaries alone; single-word labels
  ("Vivier", "Qualifié") require a state cue right before them
  ("en", "statut", …), so "dev qualifié" never triggers the filter.
- All sources are unioned and de-duplicated; the filter is only built
  when the discovered tool schema actually declares `candidateStates`.

### Applied to every search pass

The resolved filter is injected at all three execution surfaces: every
pass of the recall ladder **including the complementary titleSkills
pass** (a relaxed pass can therefore never leak other states), the
planned-inputs fallback path (`_resolve_search_filters`), and the
deterministic input builder — where a state selection alone counts as
a meaningful criterion, because "tous les candidats en Vivier" is a
legitimate browse.

### States are offered as data, not typed as text

`GET /api/candidate-states` returns normalized `{id, label}` options
from the cached dictionary (ADR-013, 6 h TTL) for the web UI's
checkbox popover next to the search input. Selected ids travel in
`filters.candidate_states`. The web UI never types or interprets state
names, keeping the "frontend does not build BoondManager queries"
boundary intact.

### Post-query filtering is display-only

`enrich_candidates` resolves `_stateId`/`_stateLabel` on **all**
results (not just the enriched slice), and `CandidateCard` gains
`state_id` alongside `state_label`. The results toolbar shows a
compact "États" dropdown with one checkbox per state present in the
received cards; checking states hides non-matching cards client-side
without any new backend query.

### Exclusion policy

"Ne plus contacter", "A SUPPRIMER", and "Proposition refusé" are in
`_EXCLUDED_STATE_KEYWORDS`: candidates in those states are removed
from results before enrichment, and `candidate_state_options` never
offers them as filter choices. One list drives both behaviors.

## Consequences

- "je veux un dev C# de 5 ans d'expérience qui est en Vivier" now
  applies a hard provider-side filter, and the checkbox path gives the
  same result with zero spelling risk. Multiple states are additive.
- The state filter survives search broadening — relaxed passes stay
  inside the selected states — at the cost of possibly empty results
  when a state is over-restrictive; the existing
  `no_results_after_fallback` messaging covers that honestly.
- Query-time state filtering costs no extra MCP calls in steady state:
  label resolution reuses the dictionary already fetched by the ladder
  (or the ADR-013 cache elsewhere).
- The conservative cue-based detection can miss exotic phrasings
  ("ceux du vivier" without "en"); the LLM extraction is the primary
  natural-language path and the checkboxes are the reliable one.
- `state_id` is a new stable card field; the frontend filter keys on
  it (falling back to the label) so renaming a state in BoondManager
  does not break bucketing mid-session.
- Excluded states are enforced by label keywords, not hardcoded ids,
  so they follow dictionary edits; a renamed excluded state (e.g.
  "Refus proposition") would need a keyword update to stay excluded.
