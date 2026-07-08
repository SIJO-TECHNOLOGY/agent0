# ADR-011 - Agent1: Candidate Data Normalization with Optional LLM Reconciliation

## Status

Accepted.

## Context

Candidate data reaches the Agent API from three sources that frequently
disagree: BoondManager structured fields, the technical document, and the
extracted CV text. Concretely, the field most users care about — years of
experience, skills, languages, job title — is often **absent from the
structured fields but present in free text** (e.g. "3+ years of hands-on
experience" only in the CV), **inconsistent across sources**, or **ambiguous**
(a CV stating an age "40 ans" on one line and "16 ans d'expérience" on another).

Before this change, ranking (`rank_candidates`) and the card mapper read raw,
incomplete BoondManager fields directly. Two classes of bug followed:

1. Skills/experience present only in free text never surfaced on the card.
2. Naive parsing mis-read experience — an age was taken as experience, and a
   "junior 0-2 ans" search returned 7-year profiles at 100% because experience
   was modelled only as a *minimum*.

We needed a single place that reconciles these sources into a clean view
*before* matching, without breaking the architecture mandate ("normalize MCP
results; never invent candidate data") and without adding uncontrolled LLM cost.

## Decision

Introduce **Agent1**, a dedicated data-quality node (`normalize_candidates` in
`app/agents/agent1/`) that runs between `enrich_candidates` and matching in both
workflows. It writes a reconciled view into each `result.data` under
`_normalized_*` keys, leaving the raw payload untouched. Agent1 has two passes:

### 1. Deterministic pass (always on)

Pure-Python heuristics, no LLM, no I/O — fast, free, idempotent.

- **Experience** is resolved from the most trustworthy source, in order: a
  *clearly stated* CV figure ("16 ans d'expérience"), then structured
  `experienceMinYears`, then the experience *level* band (`_experienceLabel`),
  then other free text. Numbers are only counted when explicitly tied to an
  experience keyword in the same clause (digit-free gap; a high-precision
  "keyword: number" form tried first), so an age line next to an experience
  line is read correctly even when PDF extraction collapses the lines.
- **Skills / languages** are unioned from structured fields plus free text
  matched against the shared `KNOWN_SKILL_PATTERNS` table; comma/newline skill
  strings are split into individual tags.
- **Conflicts** are detected (`detect_conflicts`) and recorded in
  `_normalized_conflicts` — e.g. `age_present_with_experience`,
  `experience_multiple_figures`, `experience_vs_structured_disagreement`,
  `title_seniority_mismatch`.
- **Cross-checks (comparison only).** The graduation-year estimate and the sum
  of the CV's per-role durations are computed for every candidate and compared
  against the resolved experience; a divergence ≥ 3 years raises a conflict
  (`experience_vs_graduation_disagreement` / `experience_vs_duration_disagreement`).
  The duration sum is never used as the displayed value (simultaneous roles can
  be double-counted) — only as a coherence signal.
- **Graduation fallback.** Experience is estimated from the graduation year
  (`current_year − latest education end year`, parsed from technical-document
  diplomas/training or the CV education section) when either (a) the data is
  conflicting AND no figure was explicitly stated in the CV, or (b) no
  experience figure exists anywhere AND there is no structured experience-level
  band to display. Source `graduation`. A curated level band is always
  preferred over an estimate; if no graduation year is found, the prior
  deterministic value stands.

### 2. LLM reconciliation pass (optional, off by default)

When `agent1_llm_reconciliation` is enabled, **only the candidates flagged as
conflicting** are sent — batched into a single, grounded call per search — to an
LLM "coherence judge" (`reconciler.py`) that returns a validated
`Agent1Judgement` per candidate (experience, skills, languages, title,
confidence). A judgement overrides the deterministic value only when its
`confidence ≥ agent1_confidence_threshold`.

The design choice is **"deterministic first, LLM only on conflict"**: the rule
engine is the reliable, zero-cost baseline; the non-deterministic flexibility of
an LLM is reserved for the few genuinely ambiguous cases it handles better.

### Experience as a range (matching)

Ranking now models experience as a band, not just a floor. `analyze_intent`
(and the LLM planner) populate `min_experience_years` and
`max_experience_years` (`extract_experience_bounds`; junior ≤ 2, confirmed 3-5,
senior ≥ 5 when no number is given). In `evidence_score`, a candidate whose
*known* experience exceeds the cap loses the seniority credit and the score is
multiplied by `_OVER_CAP_PENALTY` (0.4) — strongly demoted but still visible.

## What stays deterministic

The deterministic pass, conflict detection, the ranking score arithmetic, the
experience-range cap, result normalization into cards, and all guardrails are
deterministic Agent-API code. The LLM only arbitrates flagged conflicts, and
only when explicitly enabled.

## Guardrails

- **Off by default** (`AGENT1_LLM_RECONCILIATION=false`) ⇒ Agent1 is purely
  deterministic and idempotent.
- **Fail-safe.** Any LLM/parse/validation error returns no judgements, so the
  deterministic result stands (`Agent1Reconciler.reconcile` never raises).
- **Bounded cost.** Coherent candidates skip the LLM entirely; conflicting ones
  share one batched call, capped at `agent1_max_reconcile_candidates`, with
  truncated texts.
- **Grounded.** The LLM reconciles only the provided text; it must not invent
  data, per the architecture contract.
- **Card boundary.** `_normalized_*` keys must be whitelisted in
  `candidate_mapper._SAFE_INTERNAL_FIELDS` to reach the card;
  `_normalized_conflicts` is deliberately not whitelisted (internal only).
- **Import boundary.** `KNOWN_SKILL_PATTERNS` lives in the dependency-free
  `app/skill_patterns.py` to avoid a circular import (`app.services.__init__` →
  `search_service` → `graph.nodes` → Agent1).

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `agent1_llm_reconciliation` | `false` | Master switch for the LLM coherence judge. |
| `agent1_confidence_threshold` | `0.6` | Min confidence for an LLM judgement to override the deterministic value. |
| `agent1_max_reconcile_candidates` | `10` | Hard cap on candidates sent to the LLM per search. |

The LLM reconciler reuses the planner's `LLM_PROVIDER` / `LLM_MODEL` /
`LLM_API_KEY` settings.

## Consequences

- Skills, languages, and experience present only in free text now surface on the
  card; experience years are far more accurate (age ≠ experience).
- "Junior" / range searches behave correctly: over-qualified profiles are
  demoted instead of scoring 100%.
- The deterministic baseline keeps the system predictable and testable; enabling
  the LLM adds at most one batched call per search, only when conflicts exist.
- Strict idempotence holds only with the LLM pass off; with it on, conflicting
  candidates may vary run-to-run by design (tests mock the `ChatFn`).

## References

- Agent1: `app/agents/agent1/normalizer.py`, `app/agents/agent1/reconciler.py`,
  `app/skill_patterns.py`.
- Graph/nodes: `app/graph/nodes.py` (`normalize_candidates`, NodeContext
  `agent1_reconciler`), `app/graph/workflow.py`.
- Matching: `app/services/search_strategy.py` (`evidence_score`,
  `_OVER_CAP_PENALTY`), `app/graph/intent_keywords.py`
  (`extract_experience_bounds`).
- Card mapping: `app/services/candidate_mapper.py` (`_SAFE_INTERNAL_FIELDS`).
- Settings/wiring: `app/config/settings.py`, `app/api/dependencies.py`,
  `app/services/search_service.py`.
- Tests: `tests/test_agent1_normalizer.py`, `tests/test_agent1_reconciler.py`,
  `tests/test_search_strategy.py`, `tests/test_intent_keywords.py`.
- Design: `apps/agent-api/docs/langgraph-agent-design.md` (Agent1 section).
