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
  "message": "J'ai trouvé 5 profils proches de votre recherche.",
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
- Resolve dictionary-backed BoondManager IDs into labels where possible
  (experience, availability, candidate state, mobility, tools, languages,
  activity areas).
- Candidate cards may expose enriched profile fields such as `state_label`,
  `technical_summary`, `diplomas`, `expertise_areas`, `activity_areas`,
  `tools`, `languages`, `source`, and `last_update`.
- User-facing messages should stay natural and honest. Prefer "profils proches"
  and "points à confirmer" when criteria are not fully verified; do not expose
  internal warning codes or long diagnostic parentheses.
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
