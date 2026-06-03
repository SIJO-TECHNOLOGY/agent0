# Agent API Implementation Plan

## Goal

Build the MVP Python backend for natural-language candidate search orchestration.

The Agent API receives a search request, interprets the user intent, plans tool usage, calls MCP tools, evaluates results, optionally replans once, and returns a UI-oriented response for the frontend.

## MVP Scope

- Runtime baseline: Python 3.12.
- FastAPI endpoint: `POST /api/search`.
- LangGraph workflow with explicit nodes.
- MCP client abstraction for BoondManager tools.
- Typed Pydantic models for API and workflow boundaries.
- UI-oriented response models normalized from MCP results.
- Structured logging.
- pytest coverage with mocked MCP responses.

## Non-Goals

- No direct BoondManager API calls.
- No implementation of the MCP server.
- No frontend implementation.
- No persistence layer unless explicitly requested later.
- No open-ended ReAct loop or uncontrolled recursive agent execution.
- No WebSocket or bidirectional streaming in the MVP. `POST /api/search/stream` is SSE-style Agent API progress and remains separate from internal MCP transport.

## Phased Implementation

### Phase 1: Project Skeleton

- Add Python project files only when implementation begins.
- Use uv for dependency and virtual environment management.
- Create the target `app/` and `tests/` structure documented in [Project Structure](./project-structure.md).
- Keep all runtime code inside `apps/agent-api`.

### Phase 2: Configuration And Schemas

- Centralize settings for LLM provider, MCP server URL, timeouts, logging, and environment.
- Use dotenv or pydantic-settings for local configuration.
- Define request, UI response, candidate card, graph state, tool call, warning, and error schemas with Pydantic.
- Keep internal workflow metadata separate from the default frontend response.

### Phase 3: FastAPI Boundary

- Implement `POST /api/search`.
- Keep route handlers thin.
- Validate input and serialize output at the API layer.
- Delegate orchestration to an application service that invokes the LangGraph workflow.
- Return `conversation_id`, `message`, and `ui` by default.

### Phase 4: LangGraph Workflow

- Implement the required nodes:
  - `analyze_intent`
  - `build_plan`
  - `select_tools`
  - `execute_mcp_tools`
  - `evaluate_results`
  - `replan_if_needed` (deterministic fallback) / `reflect_on_results` (LLM-driven bounded replan; see ADR-010)
  - `generate_final_response`
- Keep each node small, typed, and independently testable.
- Use graph state for all workflow data rather than hidden globals.

### Phase 5: MCP Client Integration

- Add an MCP client abstraction that can discover tools and execute selected tool calls.
- Do not hard-code BoondManager API calls.
- Normalize MCP client errors into Agent API error and warning models.
- Use timeouts and bounded retries for transient failures.
- Normalize BoondManager MCP candidate results into frontend candidate card fields.
- Do not return raw MCP payloads to the frontend.

### Phase 6: Evaluation And Replanning

- Evaluate result quality after tool execution.
- Replan only when results are empty, clearly insufficient, or tool selection failed.
- In the LLM workflow the replan decision is the LLM's (`reflect_on_results`); the deterministic
  fallback applies the same conditions as rules (`replan_if_needed`). See ADR-010.
- Bound replanning with a small retry count (`max_replan_attempts`); gate cost with
  `replan_skip_score`; `use_llm_replan=false` disables the loop.
- Keep warnings and confidence in internal state or optional debug output.
- Do not include internal metadata in the default frontend response.

### Phase 7: Tests And Observability

- Add pytest tests for API validation, graph nodes, workflow execution, MCP client behavior, and error handling.
- Mock MCP tools for MVP tests.
- Add structured logs for request ID, interpreted intent, selected tools, result counts, warnings, and errors.
- Test that `/api/search` returns the UI-oriented contract and does not leak raw MCP payloads.

## Acceptance Criteria

- `POST /api/search` returns the documented UI-oriented response shape.
- The Agent API only accesses BoondManager data through MCP tools.
- BoondManager MCP results are normalized into candidate card models.
- Missing scalar or numeric fields become `null`.
- Missing list fields become `[]`.
- Candidate summaries are grounded in MCP result fields and do not invent data.
- LangGraph owns workflow state and node transitions.
- FastAPI remains a thin HTTP layer.
- Internal metadata such as interpreted intent, execution plan, tool calls, confidence, and warnings is not returned by default.
- Tests cover successful search, no results, MCP failure, invalid request, and replanning.

## Architecture Inputs

This plan implements the Agentic Backend described in the [Sijo AI Agent Architecture](../../../docs/architecture/sijo-ai-agent-architecture.md).

- [ADR-002 - MCP Client Wiring Review](../../../docs/decisions/adr-002-mcp-client-wiring-review.md) constrains MCP client selection and dependency injection.
- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) constrains health, readiness, and unavailable-MCP behavior.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) constrains async startup failure handling.
- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](../../../docs/decisions/adr-005-agent-planner-drift-from-llm-architecture.md) constrains real-mode fuzzy search to LLM-led planning over discovered MCP tool metadata.
- [ADR-006 - User-Facing Search Streaming Strategy](../../../docs/decisions/adr-006-user-facing-search-streaming-strategy.md) constrains streaming search to sanitized Agent API progress events while keeping MCP transport internal.
- [ADR-007 - LLM Tool Plan Execution Semantics](../../../docs/decisions/adr-007-llm-tool-plan-execution-semantics.md) constrains how the LLM plan executor distinguishes ordering from candidate-id fan-out and which tools may produce candidate results.
- [ADR-008 - MCP Result Envelope Normalization Boundary](../../../docs/decisions/adr-008-mcp-result-envelope-normalization-boundary.md) constrains MCP record envelope normalization to the MCP client boundary, shared between the real and mock clients.
- [ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification](../../../docs/decisions/adr-009-agent-api-milestone-1-boundary.md) constrains the Milestone 1 boundary to orchestration and frontend-contract delivery, deferring criterion-evidence work to a later milestone.
- [ADR-010 - LLM-Driven Bounded Replan](../../../docs/decisions/adr-010-llm-driven-bounded-replan.md) constrains the LLM workflow to bounded observe-then-replan, with deterministic guardrails around reflection.
- [Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop](../../../docs/architecture-transitions/bounded-react-control-loop/README.md) drives the migration from the old single-shot control-loop model to bounded ReAct.
- [Milestone 001 - Agent API MCP Fuzzy Search](../../../docs/milestones/milestone-001-agent-api-mcp-fuzzy-search.md) records the certified delivery state and reproducible verification evidence for this implementation plan.
- [Milestone 002 - Bounded ReAct Control Loop](../../../docs/milestones/milestone-002-bounded-react-control-loop.md) defines the certification target for LLM observe-then-replan behavior.
