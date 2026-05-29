# Agent API

Python backend for the Sijo AI Agent platform.

The Agent API receives natural-language search requests from the web UI, orchestrates a LangGraph workflow, calls MCP tools exposed by the BoondManager MCP server, ranks and aggregates results, and returns a structured response with an AI-generated summary.

## Status

Documentation-only guidance for the MVP.

No application source code, framework boilerplate, or `pyproject.toml` has been generated yet.

## Stack

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

## Responsibilities

- Analyze user intent.
- Build and execute a search plan.
- Select MCP tools.
- Orchestrate LangGraph nodes.
- Aggregate, deduplicate, rank, and summarize results.
- Return structured responses to the web UI.

## Non-Goals

- Do not call BoondManager APIs directly.
- Do not duplicate MCP server pagination, validation, or API abstraction logic.
- Do not implement open-ended autonomous ReAct loops for the MVP.
- Do not add framework boilerplate until implementation begins.

## MVP Endpoint

```text
POST /api/search
```

The endpoint accepts a natural-language query and optional filters, then returns interpreted intent, execution plan, tool calls, results, summary, confidence, and warnings.

## System Context

This module implements the Agentic Backend described in the [Sijo AI Agent Architecture](../../docs/architecture/sijo-ai-agent-architecture.md). It should preserve the boundary between LangGraph orchestration and deterministic MCP tool execution.

## Documentation

- [Implementation Plan](./docs/implementation-plan.md)
- [LangGraph Agent Design](./docs/langgraph-agent-design.md)
- [API Contract](./docs/api-contract.md)
- [Project Structure](./docs/project-structure.md)
- [Testing Strategy](./docs/testing-strategy.md)
- [Claude Code Instructions](./CLAUDE.md)
- [Agent API Skill](./SKILL.md)

## Decision Trail

- [ADR-002 - MCP Client Wiring Review](../../docs/decisions/adr-002-mcp-client-wiring-review.md) explains why MCP clients must be selected explicitly through configuration.
- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) defines health, readiness, and search behavior when MCP is unavailable.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) records the async startup edge case found while validating ADR-003.
- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](../../docs/decisions/adr-005-agent-planner-drift-from-llm-architecture.md) explains why real-mode fuzzy search should return to LLM-led planning over discovered MCP tools.
- [ADR-006 - User-Facing Search Streaming Strategy](../../docs/decisions/adr-006-user-facing-search-streaming-strategy.md) explains why frontend progress streaming should be SSE-style Agent API events, not exposed MCP transport.
- [ADR-007 - LLM Tool Plan Execution Semantics](../../docs/decisions/adr-007-llm-tool-plan-execution-semantics.md) explains how ordering-only `depends_on` is distinguished from candidate-id fan-out, and which tools may produce candidate results.
- [ADR-008 - MCP Result Envelope Normalization Boundary](../../docs/decisions/adr-008-mcp-result-envelope-normalization-boundary.md) explains why MCP result envelopes are unwrapped at the MCP client boundary and shared between real and mock clients.
- [ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification](../../docs/decisions/adr-009-agent-api-milestone-1-boundary.md) explains what Agent API Milestone 1 covers and which precision work is deferred to a later milestone gated by MCP-side improvements.
- [Milestone 001 - Agent API MCP Fuzzy Search](../../docs/milestones/milestone-001-agent-api-mcp-fuzzy-search.md) records the orchestration milestone with reproducible verification evidence.
