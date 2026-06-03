# ADR-010 - LLM-Driven Bounded Replan (Observe-Then-Replan)

## Context

ADR-005 made the LLM the primary real-mode planner and ADR-007 fixed its plan-execution semantics.
Through those milestones the LLM workflow (`build_llm_workflow`) was deliberately **single-shot**:
`discover_mcp_tools → plan_with_llm → execute_llm_plan → enrich_candidates → evaluate_results →
rank_candidates → generate_final_response`, with no loop-back. The only replan logic
(`replan_if_needed` / `should_replan`) lived in the **deterministic fallback** and never consulted
the LLM. "Observe-then-replan for the LLM path" was explicitly deferred to its own ADR — this one.

The triggering observation: the LLM correctly extracts criteria and a ranking priority, but when a
first search returns weak results (e.g. the top candidate for "java dev … last job in CIB" is a Java
*coach*, or too few real matches are found), nothing re-examines the outcome. The decision of
whether the results are good enough — and what to change — is exactly the kind of judgement the LLM
should make, not fixed code.

## Decision

Add an **LLM-driven, bounded reflection loop** to the LLM workflow. After ranking, a new
`reflect_on_results` node asks the LLM (`LlmPlanner.reflect`) whether one more, better-targeted
search pass is warranted; a conditional edge (`should_replan_llm`) loops back to `plan_with_llm`
carrying the LLM's `guidance`. This is "lightweight reflection" — **bounded, never autonomous**.

The LLM owns the *decision*; deterministic Agent-API code owns the *guardrails*:

1. **Hard cap.** `max_replan_attempts` (Settings, default 1, range 0–3) is checked deterministically
   before each reflection, so the LLM can never exceed the budget.
2. **Cost gate.** The reflection LLM call is skipped when results are already strong — any
   `is_full_match`, or top `score >= replan_skip_score` (default 0.8) — or when budget is spent.
3. **Fail-safe.** Any reflection or JSON-parse error yields `needs_replan=false`
   (`parse_reflection_response`), so a bad response can never start a loop.
4. **No spin.** `GraphState.replan_feedback` is the single loop signal: set only by
   `reflect_on_results` under budget, consumed and cleared by `plan_with_llm` exactly once.
5. **Kill switch.** `use_llm_replan=false` (or `max_replan_attempts=0`) ⇒ the LLM workflow is
   single-shot, identical to pre-ADR behaviour.
6. **Accumulate, don't discard.** A replan re-runs `execute_llm_plan`, which merges into
   `state.results` and de-dupes by `(source_tool, id)` — so a second pass *adds* better-targeted
   candidates rather than throwing away the first.

The reflection prompt reuses the operator-configurable planner persona (`llm_planner_role`) and asks
for a small fixed verdict `{needs_replan, reason, guidance}`. On replan, `build_planner_prompt`
appends a "PREVIOUS ATTEMPT" section with the guidance so the next plan changes its approach
(keywords / `ranking_priority` / broadened-or-dropped constraint).

This keeps the system within `CLAUDE.md`'s mandate — "Plan-and-Execute with lightweight reflection;
no fully autonomous open-ended ReAct loops."

## What stays deterministic

Plan validation (`validate_plan`), the recall-relaxation ladder, dictionary-id resolution, the
ranking score arithmetic (`evidence_score`), result normalization, and the loop guardrails remain
deterministic Agent-API code. The LLM decides: the plan, the criteria, the ranking priority, and now
the replan decision.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `use_llm_replan` | `true` | Master switch for the reflection loop; `false` ⇒ single-shot. |
| `max_replan_attempts` | `1` (≤3) | Hard cap on replan iterations. |
| `replan_skip_score` | `0.8` | Skip reflection when a full match exists or top score ≥ this. |

## Consequences

- A weak first pass can trigger at most `max_replan_attempts` extra, guided search passes; strong
  searches pay nothing (the gate skips the reflection call).
- Worst-case added cost per query is one reflection call plus one plan+search per allowed replan.
- The stream surfaces a `replan_requested` event (`decided_by: "llm"`) and a second `plan_created`
  when the LLM elects to replan, so the decision is observable.

## References

- Graph + nodes: `app/graph/workflow.py` (`build_llm_workflow`), `app/graph/nodes.py`
  (`reflect_on_results`, `should_replan_llm`, `plan_with_llm`).
- Planner: `app/services/llm_planner.py` (`LlmPlanner.reflect`, `build_reflection_prompt`,
  `parse_reflection_response`, `ReflectionVerdict`).
- State/Settings: `app/models/graph_state.py` (`replan_feedback`), `app/config/settings.py`
  (`use_llm_replan`, `replan_skip_score`, `max_replan_attempts`).
- Tests: `tests/test_llm_replan.py`.
