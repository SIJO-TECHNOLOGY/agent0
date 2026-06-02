---
name: agent-api-implementation-guidance
description: Use when implementing or modifying the Sijo Agent API module in apps/agent-api.
---

# Agent API Skill

Use this project-local skill when working on the Sijo Agent API.

## Scope

This skill applies only to `apps/agent-api`.

Do not modify `apps/web-ui`, `apps/mcp-boondmanager`, shared packages, or infrastructure unless the user explicitly asks.

## Read First

Before implementation, read these files in order:

1. [README](./README.md)
2. [Implementation Plan](./docs/implementation-plan.md)
3. [LangGraph Agent Design](./docs/langgraph-agent-design.md)
4. [API Contract](./docs/api-contract.md)
5. [Project Structure](./docs/project-structure.md)
6. [Testing Strategy](./docs/testing-strategy.md)
7. [Claude Code Instructions](./CLAUDE.md)

## Implementation Approach

- Start with project structure and configuration.
- Add typed Pydantic schemas before wiring behavior.
- Build the FastAPI layer as a thin transport boundary.
- Implement LangGraph nodes as small, testable units.
- Introduce the MCP client behind an abstraction.
- Mock MCP tool responses before depending on a live MCP server.
- Add tests as each workflow layer is introduced.
- Normalize MCP results into frontend UI response models before returning from API routes.

## Fixed Decisions

- Runtime baseline: Python 3.12.
- Package manager: uv.
- API framework: FastAPI.
- Workflow engine: LangGraph.
- Validation: Pydantic.
- Test runner: pytest.
- Architecture style: async-first.
- Agent pattern: Plan-and-Execute with lightweight reflection.

## Guardrails

- Do not call BoondManager directly.
- Do not duplicate MCP server logic.
- Do not put orchestration in route handlers.
- Do not implement open-ended ReAct loops for the MVP.
- Do not create source code unless the user requests implementation.
- Do not return raw BoondManager MCP payloads to the frontend.
- Do not expose internal agent metadata by default.

## Frontend Response Contract

`POST /api/search` should return `conversation_id`, `message`, and `ui`.

For candidate search results:

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

Candidate card values must be adapted from BoondManager MCP server results.

Use:

- `null` for unknown scalar or numeric fields.
- `[]` for missing list fields.

Never invent candidate data. Summaries may be LLM-generated only when grounded in MCP result fields.

Internal fields such as `interpreted_intent`, `execution_plan`, `tool_calls`, `confidence`, and `warnings` may exist internally or in debug mode, but are not the default frontend response.
