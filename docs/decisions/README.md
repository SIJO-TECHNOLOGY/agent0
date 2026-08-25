# Decisions

Architecture decision records and tradeoff notes.

Use this folder to record meaningful technical decisions as the project evolves.

## Decision Records

- [ADR-002 - MCP Client Wiring And Dependency Injection Review](./adr-002-mcp-client-wiring-review.md)
- [ADR-003 - Graceful MCP Degradation And Health Strategy](./adr-003-graceful-mcp-degradation-and-health-strategy.md)
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](./adr-004-asyncio-cancelled-error-mcp-startup.md)
- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](./adr-005-agent-planner-drift-from-llm-architecture.md)
- [ADR-006 - User-Facing Search Streaming Strategy](./adr-006-user-facing-search-streaming-strategy.md)
- [ADR-007 - LLM Tool Plan Execution Semantics](./adr-007-llm-tool-plan-execution-semantics.md)
- [ADR-008 - MCP Result Envelope Normalization Boundary](./adr-008-mcp-result-envelope-normalization-boundary.md)
- [ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification](./adr-009-agent-api-milestone-1-boundary.md)
- [ADR-010 - LLM-Driven Bounded Replan](./adr-010-llm-driven-bounded-replan.md) - records the bounded ReAct/control-loop decision for LLM observe-then-replan.
- [ADR-011 - Agent1: Candidate Data Normalization](./adr-011-agent1-candidate-data-normalization.md) - records the deterministic-first data-quality layer with optional, conflict-only LLM reconciliation.
- [ADR-012 - Reflection Decides Clarify-or-Retry](./adr-012-clarify-or-retry.md) - the post-ranking reflection may ask the user to clarify (unresolved parameter) instead of accepting or retrying.
- [ADR-013 - TTL Caching Of Semi-Stable MCP Results](./adr-013-mcp-result-caching.md) - in-process TTL cache for the dictionary, CV text, and technical documents; volatile candidate data is never cached.
