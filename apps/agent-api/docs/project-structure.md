# Project Structure

This document describes the target structure for future implementation. Do not create source code until implementation is requested.

## Target Layout

```text
apps/agent-api/
├── app/
│   ├── api/
│   ├── agents/
│   │   └── agent1/          # candidate data-normalisation (Agent1)
│   ├── graph/
│   ├── services/
│   ├── mcp/
│   ├── models/
│   ├── config/
│   ├── skill_patterns.py    # shared, dependency-free skill regex table
│   └── main.py
├── scripts/                 # operational helpers (e.g. fetch_candidate.py)
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
| `app/agents/agent1` | Agent1 candidate data-normalisation node: pure-Python heuristics that reconcile experience, skills, languages, and title across BoondManager fields, the technical document, and the CV. No LLM, no I/O. |
| `app/graph` | LangGraph state, graph construction, node definitions, and transition logic. |
| `app/services` | Application services that coordinate graph execution and response assembly. |
| `app/mcp` | MCP client integration, tool discovery, tool execution, and MCP error mapping. |
| `app/models` | Pydantic schemas for API contracts, graph state, tool calls, warnings, and errors. |
| `app/config` | Runtime settings, environment loading, and dependency configuration. |
| `app/skill_patterns.py` | Dependency-free `KNOWN_SKILL_PATTERNS` table shared by `candidate_mapper` and Agent1; kept outside `app.services` to avoid a circular import. |
| `app/main.py` | FastAPI application factory or app entrypoint. |
| `scripts` | Operational/diagnostic helpers run from the terminal (e.g. `fetch_candidate.py`, which pulls a candidate's detail, technical document, and CV directly via MCP). |
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
graph -> agents -> models        # graph.nodes invokes Agent1
graph -> models
mcp -> models
config -> all runtime setup
agents, services -> skill_patterns   # leaf module, imports nothing from app
```

Avoid circular imports by keeping shared schemas in `app/models`, runtime
settings in `app/config`, and cross-cutting leaf data (e.g. `KNOWN_SKILL_PATTERNS`)
in dependency-free modules like `app/skill_patterns.py`. Concretely: Agent1 must
not import from `app.services` (that package's `__init__` pulls in
`search_service` → `graph.nodes` → Agent1), so shared skill data lives in
`app/skill_patterns.py` instead.

## Architecture Inputs

- [Sijo AI Agent Architecture](../../../docs/architecture/sijo-ai-agent-architecture.md) defines the module boundaries between web UI, Agent API, MCP server, and BoondManager.
- [ADR-002 - MCP Client Wiring Review](../../../docs/decisions/adr-002-mcp-client-wiring-review.md) explains why MCP integration belongs behind an explicit client abstraction and composition boundary.
