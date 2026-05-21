# Agent API Implementation Plan

## Goal

Build the MVP Python backend for natural-language BoondManager search orchestration.

The Agent API receives a search request, interprets the user intent, plans tool usage, calls MCP tools, evaluates results, optionally replans once, and returns structured results plus an AI summary.

## MVP Scope

- Runtime baseline: Python 3.12.
- FastAPI endpoint: `POST /api/search`.
- LangGraph workflow with explicit nodes.
- MCP client abstraction for BoondManager tools.
- Typed Pydantic models for API and workflow boundaries.
- Structured logging.
- pytest coverage with mocked MCP responses.

## Non-Goals

- No direct BoondManager API calls.
- No implementation of the MCP server.
- No frontend implementation.
- No persistence layer unless explicitly requested later.
- No open-ended ReAct loop or uncontrolled recursive agent execution.
- No streaming response in the MVP, but keep the contract compatible with future streaming.

## Phased Implementation

### Phase 1: Project Skeleton

- Add Python project files only when implementation begins.
- Use uv for dependency and virtual environment management.
- Create the target `app/` and `tests/` structure documented in [Project Structure](./project-structure.md).
- Keep all runtime code inside `apps/agent-api`.

### Phase 2: Configuration And Schemas

- Centralize settings for LLM provider, MCP server URL, timeouts, logging, and environment.
- Use dotenv or pydantic-settings for local configuration.
- Define request, response, graph state, tool call, warning, and error schemas with Pydantic.

### Phase 3: FastAPI Boundary

- Implement `POST /api/search`.
- Keep route handlers thin.
- Validate input and serialize output at the API layer.
- Delegate orchestration to an application service that invokes the LangGraph workflow.

### Phase 4: LangGraph Workflow

- Implement the required nodes:
  - `analyze_intent`
  - `build_plan`
  - `select_tools`
  - `execute_mcp_tools`
  - `evaluate_results`
  - `replan_if_needed`
  - `generate_final_response`
- Keep each node small, typed, and independently testable.
- Use graph state for all workflow data rather than hidden globals.

### Phase 5: MCP Client Integration

- Add an MCP client abstraction that can discover tools and execute selected tool calls.
- Do not hard-code BoondManager API calls.
- Normalize MCP client errors into Agent API error and warning models.
- Use timeouts and bounded retries for transient failures.

### Phase 6: Evaluation And Replanning

- Evaluate result quality after tool execution.
- Replan only when results are empty, clearly insufficient, or tool selection failed.
- Bound replanning with a small retry count.
- Add warnings when the final response has partial or low-confidence results.

### Phase 7: Tests And Observability

- Add pytest tests for API validation, graph nodes, workflow execution, MCP client behavior, and error handling.
- Mock MCP tools for MVP tests.
- Add structured logs for request ID, interpreted intent, selected tools, result counts, warnings, and errors.

## Acceptance Criteria

- `POST /api/search` returns the documented response shape.
- The Agent API only accesses BoondManager data through MCP tools.
- LangGraph owns workflow state and node transitions.
- FastAPI remains a thin HTTP layer.
- Results include a summary, confidence score, and warnings array.
- Tests cover successful search, no results, MCP failure, invalid request, and replanning.

## Related Architecture Decisions

- [ADR-002 - MCP Client Wiring Review](../../../docs/decisions/adr-002-mcp-client-wiring-review.md)
- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md)
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md)
