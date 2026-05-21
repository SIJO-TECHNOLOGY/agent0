# Testing Strategy

## Goals

Tests should prove that the Agent API validates requests, orchestrates LangGraph correctly, calls MCP through the client abstraction, handles failures safely, and returns the documented response shape.

Use pytest for all tests.

## Test Categories

| Category | Purpose |
| --- | --- |
| API contract tests | Validate `POST /api/search` request and response behavior. |
| Schema tests | Verify Pydantic validation for requests, responses, graph state, tool calls, warnings, and errors. |
| Graph node tests | Test each LangGraph node independently with controlled state. |
| Workflow tests | Run the full graph with mocked MCP outputs. |
| MCP client tests | Verify tool discovery, tool execution, timeout handling, and error mapping with mocks. |
| Error handling tests | Confirm safe responses for invalid input, MCP failures, empty results, and partial results. |

## Async Rules

- Use async tests for FastAPI, MCP client, LLM, and graph execution paths.
- Avoid blocking I/O in async code.
- Use explicit timeouts in tests involving external-style clients, even when mocked.

## Fixtures

Recommended fixtures:

- Valid search request.
- Invalid empty query request.
- Mock MCP tool registry.
- Mock successful MCP response.
- Mock empty MCP response.
- Mock MCP validation error.
- Mock transient MCP failure.
- Deterministic LLM or planner stub.

## Required MVP Scenarios

- Successful search returns interpreted intent, plan, tool calls, results, summary, confidence, and warnings.
- Empty results return a valid response with a useful summary and warning.
- Invalid request returns a structured validation error.
- MCP validation failure returns a safe error or warning without raw provider details.
- Transient MCP failure is retried only within configured limits.
- Replanning occurs only when documented conditions are met.
- Direct BoondManager access is not present in tests or implementation.

## Mocking Strategy

- Mock MCP tools instead of calling a live MCP server in unit tests.
- Use integration tests with a fake MCP server only after the client abstraction exists.
- Keep LLM behavior deterministic in tests through stubs or fixed responses.

## Acceptance Criteria

- Tests can run locally with uv and pytest once implementation exists.
- Tests do not require BoondManager credentials.
- Tests verify the public API contract and core workflow behavior.
- Tests cover both successful and degraded execution paths.

## Review-Driven Test Coverage

- [ADR-002 - MCP Client Wiring Review](../../../docs/decisions/adr-002-mcp-client-wiring-review.md) requires tests for mock-vs-real MCP selection and prevention of silent fallback.
- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) requires tests for `/api/health`, `/api/ready`, and structured `503` behavior when MCP is unavailable.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) requires tests for startup `asyncio.CancelledError` handling in the MCP connection path.
