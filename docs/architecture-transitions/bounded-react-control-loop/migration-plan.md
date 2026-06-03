# Migration Plan

## Headline

Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop

## Phase 1: Document The Shift

Status: in progress.

- Add ADR-010 as the formal decision record.
- Add this transition track as the migration driver.
- Update global architecture and Agent API docs so bounded ReAct is visible outside local implementation files.
- Remove stale single-shot and future-only streaming language.

Exit gate:

- ADR-010, the transition track, and Milestone 002 are linked from the project docs.

## Phase 2: Introduce Bounded Reflection

Status: in progress.

- Add `reflect_on_results` to the LLM workflow after ranking.
- Add `should_replan_llm` as the conditional loop edge.
- Add `GraphState.replan_feedback`.
- Add `LlmPlanner.reflect` and the reflection verdict parser.
- Add settings for `use_llm_replan` and `replan_skip_score`.

Exit gate:

- Weak ranked results can trigger one LLM-guided replan within `max_replan_attempts`.
- Strong ranked results skip the reflection call.
- Malformed reflection output cannot loop.

## Phase 3: Align Streaming And Observability

Status: planned.

- Ensure `replan_requested` includes `decided_by: "llm"`.
- Ensure the second pass emits a second `plan_created` and `plan_validated`.
- Keep event payloads sanitized and product-level.
- Add or update stream tests for the replan event sequence.

Exit gate:

- A streaming search can show the observe-then-replan path without exposing raw MCP payloads or chain-of-thought.

## Phase 4: Certify Milestone 002

Status: planned.

- Run the focused unit tests for LLM reflection and loop routing.
- Run workflow or stream tests that exercise the end-to-end loop.
- Add a manual SSE verification shape against a live or controlled MCP setup.
- Mark Milestone 002 achieved only when reproducible evidence exists.

Exit gate:

- `docs/milestones/milestone-002-bounded-react-control-loop.md` moves from planned/in progress to achieved with evidence.

## Phase 5: Retire Stale Mental Models

Status: planned.

- Stop describing the LLM workflow as single-shot except when `use_llm_replan=false`.
- Keep deterministic fallback documented as a fallback, not the primary real-mode control loop.
- Preserve "no open-ended autonomous ReAct loops" as a safety invariant.

Exit gate:

- Searches for stale phrases return no contradictory project docs.
