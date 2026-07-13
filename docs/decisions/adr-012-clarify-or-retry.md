# ADR-012 - Reflection Decides Clarify-or-Retry

## Status

Accepted.

## Context

ADR-010 gave the LLM workflow a bounded, observe-then-replan loop: after ranking,
`reflect_on_results` asks the LLM whether ONE more, better-targeted search pass
is warranted. The only two outcomes were **accept** or **retry**.

But retrying blindly does not help when the first search failed for lack of
information rather than a poor plan — most notably when a **query parameter
could not be resolved**: an unrecognised technology/skill, an unknown location
or company, contradictory criteria (junior + 15 years), or a query too vague to
target. In those cases the right move is to **ask the user**, not to widen the
search. The frontend already supports a `clarification` UI type (form →
`interaction` answers merged back into the query), but the backend never emitted
it from the reflection.

## Decision

Extend the existing post-ranking reflection to a **three-way decision** the LLM
makes itself: **accept / retry / clarify**.

- `ReflectionVerdict` gains `needs_clarification`, `clarification_question`, and
  `clarification_fields`. The reflection prompt instructs the LLM to ASK when a
  retry would not help without more information — primarily an unresolved or
  ambiguous parameter — and to prefer accept when unsure (don't pester).
- `reflect_on_results` reads the verdict: **clarification takes precedence over
  replan**. On clarify it sets `GraphState.clarification_question` /
  `clarification_fields` and does NOT set `replan_feedback`, so the run
  finalizes without another search pass.
- `search_service` emits a `clarification` UI (`ClarificationUI`: title +
  questions) instead of candidate cards when `clarification_question` is set.
- The reflection is given a compact criteria summary
  (`_reflection_criteria_summary`: interpreted entities/constraints + resolution
  warning codes + candidate count) so it can spot an unresolved parameter.

The LLM owns the decision; deterministic code owns the guardrails.

## Guardrails

- **Bounded by the existing reflection gate.** Clarification only happens inside
  the same reflection call (gated by `use_llm_replan`, `max_replan_attempts`,
  and the strong-results cost gate) — no new loop.
- **At most one clarification per request** (`_already_clarified`): once asked,
  the run won't ask again, avoiding back-and-forth pestering.
- **Kill switch.** `allow_clarification=false` ⇒ the reflection only
  accepts/retries (pre-ADR behaviour).
- **Fail-safe.** A malformed reflection parses to an all-false verdict, so it
  can neither loop nor raise a spurious clarification.
- **No card leakage.** The clarification response carries no candidates; the
  `/api/chat` adapter handles a UI without a `candidates` field.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `allow_clarification` | `true` | Let the reflection ask the user to clarify. `false` ⇒ accept/retry only. |

Clarification still requires the LLM workflow and a reflection budget
(`use_llm_planner=true`, `max_replan_attempts ≥ 1`).

## Consequences

- A query whose parameter can't be resolved gets a targeted question instead of
  a confusing empty/weak result set; the answer flows back via `interaction`.
- One extra reflection-driven outcome, no extra LLM call beyond the existing
  reflection, and no new loop.

## References

- Nodes: `app/graph/nodes.py` (`reflect_on_results`,
  `_reflection_criteria_summary`, `_already_clarified`).
- Planner: `app/services/llm_planner.py` (`ReflectionVerdict`,
  `build_reflection_prompt`, `reflect`).
- Response: `app/services/search_service.py` (`_clarification_response`),
  `app/models/api.py` (`ClarificationUI`), `app/models/graph_state.py`.
- Settings: `app/config/settings.py` (`allow_clarification`).
- Frontend: `apps/web-ui/app.js` (`renderClarificationForm`,
  `submitClarification`).
- Tests: `tests/test_llm_replan.py`, `tests/test_clarification_response.py`.
- Builds on [ADR-010](./adr-010-llm-driven-bounded-replan.md).
