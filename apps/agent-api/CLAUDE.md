# Claude Code Instructions: Agent API

This file defines implementation rules for Claude Code when working in `apps/agent-api`.

## Scope

Work only inside `apps/agent-api` unless the user explicitly expands the scope.

Before implementation, read:

- [README](./README.md)
- [Implementation Plan](./docs/implementation-plan.md)
- [LangGraph Agent Design](./docs/langgraph-agent-design.md)
- [API Contract](./docs/api-contract.md)
- [Project Structure](./docs/project-structure.md)
- [Testing Strategy](./docs/testing-strategy.md)
- [Bounded ReAct Control-Loop Transition](../../docs/architecture-transitions/bounded-react-control-loop/README.md)

## Required Stack

- Python 3.12
- FastAPI
- LangGraph
- LangChain ecosystem
- Pydantic
- MCP client integration
- pytest
- uv
- dotenv or pydantic-settings
- Async-first architecture

## Architecture Boundaries

The Agent API owns:

- Reasoning.
- Planning.
- Orchestration.
- Ranking.
- Aggregation.
- Summarization.
- Normalization of MCP results into frontend UI response models.

The MCP BoondManager server owns:

- MCP tool exposure.
- BoondManager API abstraction.
- Deterministic tool execution.
- Input schema validation.
- Pagination and provider error normalization.

The Agent API must not:

- Call BoondManager APIs directly.
- Duplicate MCP server business data access logic.
- Embed BoondManager-specific pagination or authentication behavior.
- Turn FastAPI route handlers into orchestration logic.
- Return raw BoondManager MCP payloads to the frontend.

## Agent Pattern

Use Plan-and-Execute with lightweight reflection.

The MVP workflow is:

1. Intent Analysis
2. Build Plan
3. Select MCP Tools
4. Execute MCP Tools
5. Evaluate Results
6. Re-plan if needed
7. Generate Final Response

### LLM-driven replan (bounded reflection)

In the **LLM workflow** (`USE_LLM_PLANNER=true`), the **replan decision is made by the LLM**, not
by deterministic code. After ranking, a `reflect_on_results` node asks the LLM (via
`LlmPlanner.reflect`) whether the ranked candidates adequately answer the query; a conditional edge
(`should_replan_llm`) loops back to `plan_with_llm` with the LLM's `guidance` when it says replan.
This is the "lightweight reflection" above — it is **bounded, not autonomous**:

- Hard cap: `max_replan_attempts` (Settings, default 1, ≤3) — checked deterministically before each
  reflection, so the LLM can never exceed it.
- Cost gate: the reflection LLM call is skipped when results are already strong (a full match, or
  top score ≥ `replan_skip_score`) or the budget is spent.
- Fail-safe: any reflection/parse error ⇒ no replan.
- Kill switch: `use_llm_replan=false` (or `max_replan_attempts=0`) ⇒ the LLM workflow is single-shot.
- Loop signal: `GraphState.replan_feedback` is set only by `reflect_on_results` (under budget) and
  cleared by `plan_with_llm` on consumption, so the loop cannot spin.

The deterministic fallback workflow keeps its own rule-based `replan_if_needed` (widen the plan on
empty results) — unchanged. What the LLM owns vs what stays deterministic: the LLM decides the plan,
criteria, ranking priority, and now the replan decision; Agent-API code still owns plan validation,
the recall-relaxation ladder, the ranking score arithmetic, and the bounded loop guardrails.

Do not implement:

- Fully autonomous open-ended ReAct loops.
- Uncontrolled recursive execution.
- Self-modifying workflows.

## Implementation Rules

- Keep FastAPI route handlers thin.
- Put workflow logic in LangGraph nodes and services.
- Use typed Pydantic schemas at API, graph state, and service boundaries.
- Prefer async functions for I/O, HTTP, MCP calls, and LLM calls.
- Make MCP tools dynamically discoverable where practical.
- Keep prompt templates versioned and reviewable.
- Use structured logging with request IDs or correlation IDs.
- Design response contracts so SSE or WebSocket streaming can be added later.
- Return `conversation_id`, `message`, and `ui` by default from `POST /api/search`.
- Keep internal agent metadata out of the default frontend response.

## Frontend Response Contract

The frontend expects UI-oriented responses. For candidate search, use:

```json
{
  "conversation_id": "conv_123",
  "message": "I found 5 candidates matching your search.",
  "ui": {
    "type": "candidate_cards",
    "candidates": []
  }
}
```

Candidate card values must be normalized from BoondManager MCP results.

Rules:

- Use `null` for unknown scalar or numeric fields.
- Use `[]` for missing list fields.
- Never invent candidate data.
- LLM-generated summaries must be grounded in MCP result fields.
- Do not expose `interpreted_intent`, `execution_plan`, `tool_calls`, `confidence`, or `warnings` by default.
- These metadata fields may exist internally or in explicit debug mode only.

Future UI types may include `mission_cards`, `client_cards`, `table`, `clarification_request`, and `error_message`, but do not emit them until the frontend supports them.

## Configuration

- Load configuration from environment variables.
- Use `.env` only for local development.
- Never commit real secrets.
- Keep LLM, MCP server, logging, and runtime settings centralized.

## Testing

- Use pytest.
- Mock MCP tool responses in MVP tests.
- Test graph nodes independently.
- Test the full search workflow with controlled fake MCP responses.
- Do not write tests that call BoondManager directly.

## Acceptance Criteria

An implementation is acceptable when:

- `POST /api/search` follows the documented API contract.
- LangGraph owns workflow state and transitions.
- MCP is the only path to BoondManager data.
- MCP results are normalized into UI-friendly response models.
- Error handling is structured and user-safe.
- Tests cover API validation, graph behavior, MCP client behavior, and failure cases.
