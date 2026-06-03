# Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop

## Why This Exists

ADR-005 corrected the first planning drift: deterministic keyword and tool heuristics were accumulating in the Agent API because the LLM planner did not exist yet. ADR-010 corrects the next layer: the LLM planner existed, but the LLM workflow still made only one plan and never observed whether execution produced a good answer.

That made the Agent API partly LLM-led and partly executor-led. The LLM interpreted the query and produced a plan, but deterministic code owned the post-result decision of whether to continue, broaden, enrich, or stop.

## Why This Is A Paradigm Shift

The core change is decision authority inside the agent control loop.

Before:

```text
LLM decides initial plan.
Agent API code executes and applies fixed post-result behavior.
```

After:

```text
LLM decides initial plan.
Agent API code executes and summarizes observations.
LLM decides whether another bounded pass is worthwhile.
Agent API code validates, bounds, and executes the decision.
```

The runtime surface can remain stable, but the internal thinking pattern changes from single-shot planning to bounded observe-then-replan.

## What Changes

- The LLM owns the replan decision in the LLM workflow.
- The LLM receives sanitized observations about ranked candidate results.
- The LLM returns a small structured reflection verdict: `needs_replan`, `reason`, and `guidance`.
- `replan_feedback` carries guidance into the next planning pass and is cleared when consumed.
- The stream exposes the decision through `replan_requested` with `decided_by: "llm"`.

## What Stays Invariant

- MCP remains the only path to BoondManager data.
- The MCP server remains deterministic and non-intelligent.
- LangGraph owns state transitions and loop bounds.
- Tool plans are validated against discovered MCP tool schemas before execution.
- Raw MCP and BoondManager payloads are never sent to the frontend by default.
- Chain-of-thought is never streamed or exposed.
- A malformed reflection response fails closed and cannot start a loop.
- `use_llm_replan=false` or `max_replan_attempts=0` restores single-shot behavior.

## Naming

Use this transition name consistently:

```text
Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop
```

Use "bounded ReAct" carefully. In this project it means observe-then-replan under LangGraph guardrails, not uncontrolled autonomous tool use.
