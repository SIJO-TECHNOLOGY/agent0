# Safety Invariants

## Headline

Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop

## Core Boundary Invariants

- MCP remains the only path from the Agent API to BoondManager data.
- The MCP server remains deterministic and non-intelligent.
- The frontend never consumes raw MCP or BoondManager payloads by default.
- FastAPI route handlers stay thin and delegate orchestration to the service/workflow layer.

## Tool Execution Invariants

- The LLM may plan only against discovered MCP tool names.
- Tool inputs must be validated against discovered input schemas before execution.
- Unknown tools, unknown fields, missing required fields, and invalid fan-out requests are rejected before tool calls.
- Fan-out remains bounded by `max_enrichments`.
- Non-candidate tools must not pollute candidate ranking or counters.

## Loop Invariants

- `max_replan_attempts` is a deterministic hard cap.
- `use_llm_replan=false` disables LLM-driven reflection.
- `max_replan_attempts=0` disables replan even if reflection is enabled.
- `replan_feedback` is the only LLM workflow loop signal.
- `replan_feedback` is consumed exactly once and then cleared.
- Reflection errors, malformed JSON, empty guidance, or no `reflect` capability all stop the loop.

## Observation Invariants

- Reflection receives sanitized result summaries, not raw payloads.
- No chain-of-thought is exposed to the frontend or reused as observation input.
- Secrets, credentials, tokens, cookies, stack traces, and raw CV bodies are never included in reflection observations.
- Stream events expose progress and safe reasons, not private reasoning.

## User-Facing Invariants

- The final response remains `conversation_id`, `message`, and `ui`.
- Candidate cards are grounded in MCP result fields.
- Missing scalar values remain `null`; missing list values remain `[]`.
- Messaging must not claim that all natural-language criteria were verified unless the evidence path supports that claim.

## Operational Invariants

- MCP unavailability remains explicit through health/readiness/search behavior.
- The Agent API must not silently fall back to mock MCP in real mode.
- Configuration controls should be visible in settings and testable.
- Worst-case LLM cost is bounded by planner calls plus at most one reflection call and one additional plan per allowed replan attempt.
