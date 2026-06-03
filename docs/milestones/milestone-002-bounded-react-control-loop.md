# Milestone 002 - Bounded ReAct Control Loop

## Status

Delivered

## Date

2026-06-03

## Objective

Certify that the Agent API LLM workflow has migrated from single-shot planning to a bounded ReAct-style observe-then-replan control loop: the LLM can inspect sanitized ranked-result observations, decide whether one more guided search pass is warranted, and feed guidance back into planning while LangGraph enforces hard safety bounds.

## Scope

This milestone covers the control-loop transition for the Agent API LLM workflow:

- LLM-driven reflection after ranked results.
- Bounded loop-back from `reflect_on_results` to `plan_with_llm`.
- One-time `replan_feedback` consumption.
- Cost and safety gates through `use_llm_replan`, `max_replan_attempts`, and `replan_skip_score`.
- User-safe streaming observability for LLM replan decisions.

Not in scope: unbounded autonomous ReAct loops, direct BoondManager access, chain-of-thought streaming, frontend redesign, or MCP contract redesign.

## Acceptance Criteria

- [x] A weak first pass can trigger LLM reflection and set `replan_feedback`.
- [x] LLM guidance is consumed exactly once by the next planning pass and then cleared.
- [x] The loop respects `max_replan_attempts` regardless of the LLM verdict.
- [x] Strong results skip reflection through the full-match or `replan_skip_score` gate.
- [x] Malformed reflection output, reflection exceptions, empty guidance, or missing `reflect` capability cannot start a loop.
- [x] `use_llm_replan=false` or `max_replan_attempts=0` restores single-shot LLM workflow behavior.
- [x] The streaming path emits `replan_requested` with `decided_by: "llm"` when the LLM elects to replan.
- [x] No reflection observation or stream event exposes raw MCP payloads, raw BoondManager payloads, secrets, stack traces, or chain-of-thought.

## Verification Evidence

Delivered verification evidence (2026-06-03):

- **Automated:** `cd apps/agent-api && uv run pytest` → **360 passed**, including
  `apps/agent-api/tests/test_llm_replan.py` (10 tests: reflection gates — budget/strong-results/
  flag/missing-`reflect`/error fail-safe; `should_replan_llm` routing; one-time `replan_feedback`
  consumption; and an end-to-end one-bounded-replan workflow run) and `test_logging_trace.py`.
- **Live SSE check** against the running MCP stack, query
  `"I am searching a java dev with 10 yrs experiences whose last job is in CIB"`:
  the stream emitted `replan_requested` with `decided_by: "llm"` and a reflection `reason`/`guidance`,
  followed by a second `plan_created` that consumed the guidance, and terminated with
  `final_response`. The post-fix ranking surfaced the CIB Java developer (Antoni Galmiche) above the
  Java coach (Jerome Moliere). Strong queries (e.g. the named-person query, a full-score match)
  emitted **no** `replan_requested` — the `replan_skip_score` gate skipped the reflection call.
- **Observability:** the readable `agent.trace` decision log renders the chain
  `SEARCH → PLAN(LLM) → search → RANKED → ⟲ REPLAN(decided by llm)+guidance → PLAN(LLM) → RESULT`,
  and the web-ui progress bubble surfaces the replan step with its reason.

## Known Limitations

- This milestone certifies the bounded control loop, not perfect search precision.
- Evidence verification remains gated by reliable MCP-side evidence tools.
- The deterministic fallback workflow remains available for mock/test/local no-LLM modes.

## Related ADRs And Transition Track

- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](../decisions/adr-005-agent-planner-drift-from-llm-architecture.md)
- [ADR-010 - LLM-Driven Bounded Replan](../decisions/adr-010-llm-driven-bounded-replan.md)
- [Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop](../architecture-transitions/bounded-react-control-loop/README.md)

## Next Milestone Candidates

- Evidence-backed criterion verification once MCP technical-document data is reliable.
- UI affordances that distinguish keyword matches, visible-evidence matches, and fully verified matches.
- Optional bidirectional controls such as user cancellation, clarification, or approval-before-tool-call.
