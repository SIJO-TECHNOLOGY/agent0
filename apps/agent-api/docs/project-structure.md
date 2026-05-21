# Project Structure

This document describes the target structure for future implementation. Do not create source code until implementation is requested.

## Target Layout

```text
apps/agent-api/
├── app/
│   ├── api/
│   ├── graph/
│   ├── services/
│   ├── mcp/
│   ├── models/
│   ├── config/
│   └── main.py
├── tests/
├── docs/
├── CLAUDE.md
├── SKILL.md
├── pyproject.toml
└── README.md
```

## Folder Responsibilities

| Path | Responsibility |
| --- | --- |
| `app/api` | FastAPI routers, request validation, and response serialization. |
| `app/graph` | LangGraph state, graph construction, node definitions, and transition logic. |
| `app/services` | Application services that coordinate graph execution and response assembly. |
| `app/mcp` | MCP client integration, tool discovery, tool execution, and MCP error mapping. |
| `app/models` | Pydantic schemas for API contracts, graph state, tool calls, warnings, and errors. |
| `app/config` | Runtime settings, environment loading, and dependency configuration. |
| `app/main.py` | FastAPI application factory or app entrypoint. |
| `tests` | pytest suites for API, graph, MCP client, services, and error behavior. |
| `docs` | Implementation guidance and architecture notes. |

## Structural Rules

- Keep API handlers thin.
- Keep LangGraph node logic outside route files.
- Keep MCP integration behind a small client abstraction.
- Keep Pydantic models close to boundary definitions.
- Keep prompts reviewable and versioned if prompt files are introduced later.
- Do not place BoondManager API client code in this module.

## Dependency Direction

Preferred dependency flow:

```text
api -> services -> graph -> mcp
api -> models
services -> models
graph -> models
mcp -> models
config -> all runtime setup
```

Avoid circular imports by keeping shared schemas in `app/models` and runtime settings in `app/config`.

## Related Architecture Decisions

- [ADR-002 - MCP Client Wiring Review](../../../docs/decisions/adr-002-mcp-client-wiring-review.md)
- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md)
