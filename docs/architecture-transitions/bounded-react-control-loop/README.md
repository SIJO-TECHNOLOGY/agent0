# Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop

## Purpose

This transition track drives the Agent API migration from a single-shot LLM planner plus deterministic executor adjustments to a bounded ReAct-style control loop.

The change is larger than an ADR because it changes the agent control loop: the LLM now observes ranked results and decides whether another guided search pass is warranted, while LangGraph keeps execution bounded, validated, and auditable.

## Status

In progress.

ADR-010 records the decision. This transition track describes how the system moves through the architectural shift. Milestone 002 will certify that the behavior shipped with reproducible evidence.

## Current vs Target

Current pre-transition shape:

```text
LLM plans once -> LangGraph executes -> deterministic code adjusts/ranks -> final response
```

Target bounded ReAct shape:

```text
LLM plans -> LangGraph acts -> Agent API observes -> LLM reflects -> replan or stop
```

This is not an open-ended autonomous ReAct loop. The loop is bounded by `max_replan_attempts`, guarded by `use_llm_replan`, validated against discovered MCP tool schemas, and fail-safe when reflection output is malformed.

## Track Documents

- [Architecture Change Brief](./architecture-change-brief.md) - why this is a paradigm shift and what stays invariant.
- [Target Control Loop Spec](./target-control-loop-spec.md) - the desired bounded observe-then-replan state machine.
- [Prompt And Observation Contract](./prompt-observation-contract.md) - what the LLM may see and return during reflection.
- [Migration Plan](./migration-plan.md) - phased rollout gates for docs, code, tests, and certification.
- [Safety Invariants](./safety-invariants.md) - guardrails that must survive the migration.

## Related Records

- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](../../decisions/adr-005-agent-planner-drift-from-llm-architecture.md)
- [ADR-010 - LLM-Driven Bounded Replan](../../decisions/adr-010-llm-driven-bounded-replan.md)
- [Milestone 001 - Agent API MCP Fuzzy Search](../../milestones/milestone-001-agent-api-mcp-fuzzy-search.md)
- [Milestone 002 - Bounded ReAct Control Loop](../../milestones/milestone-002-bounded-react-control-loop.md)
