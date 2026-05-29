# Claude Code Instructions: MCP Server

This file defines implementation rules for Claude Code when working in the MCP Server project.

## Scope

Work only inside this project unless the user explicitly expands the scope.

Before implementation, read:

* [Project Overview](#project-overview)
* [Architecture Boundaries](#architecture-boundaries)
* [MCP Tools Specification](#mcp-tools-specification)
* [Implementation Rules](#implementation-rules)
* [Package Structure](#package-structure)

---

## Project Overview

This project is an MCP (Model Context Protocol) Server — the standardized gateway between AI agents and BoondManager APIs, dedicated to HR and recruitment teams.

The AI assistant helps recruiters:
* Simplify candidate search
* Accelerate sourcing workflows
* Reduce repetitive actions
* Improve access to recruitment information
* Assist decision-making during recruitment processes

---

## Required Stack

* Java 21
* Spring Boot 4.x
* Spring AI
* Spring WebFlux (WebClient)
* Constructor injection only
* Records and immutable objects preferred

---

## Architecture Boundaries

The MCP Server owns:

* MCP tool exposure.
* BoondManager API abstraction.
* Transport handling (Streamable HTTP).
* Request validation.
* Correlation ID propagation.
* Authentication and communication with BoondManager APIs.
* DTO normalization and query parameter construction.
* Business-oriented deterministic recruitment tools.

The Python Backend (FastAPI + LangGraph) owns:

* AI orchestration.
* LangGraph workflows.
* Candidate ranking and scoring.
* Reasoning and business intelligence.
* Conversation memory and agent workflows.
* MCP tool orchestration.

The Python backend must never call BoondManager APIs directly.

All BoondManager interactions must go through the MCP Server.

The MCP Server must not:

* Implement autonomous AI reasoning.
* Implement LangGraph workflows or agent state machines.
* Expose raw BoondManager API endpoints.
* Contain opaque AI scoring logic.
* Use hardcoded enums for reference data (skills, contract types, etc.).

---

## Agent Pattern

All BoondManager access is centralized inside the MCP Server.

The Python backend consumes MCP tools instead of directly calling BoondManager APIs.

The MCP Server exposes deterministic, business-oriented tools. Tools must:

* Express business intent (not CRUD operations).
* Remain deterministic and stateless.
* Be composable and reusable by AI agents.
* Encapsulate BoondManager API complexity.
* Dynamically resolve all reference data through dictionary endpoints.

Do not implement:

* Custom MCP dispatcher or tool registry.
* ChatClient architecture.
* Autonomous AI decision-making inside tools.
* Hidden ranking or scoring logic inside the MCP layer.

---

## MCP Tools Specification

### 1. Implemented — Candidate Search & Exploration

| Tool | Class | Description |
|---|---|---|
| `getDictionary` | `BoondDictionaryTool` | Retrieves all BoondManager reference data (diploma levels, contract types, availability types, experience levels, expertise areas, activity sectors, tools, languages, candidate states). Must be called before `searchCandidates` to resolve human-readable values to their IDs. |
| `searchCandidates` | `CandidateSearchTool` | Searches candidates with optional filters: keywords (full-text), state, availabilityType, availabilityDate, contractType, experience, training, expertiseAreas, activityAreas, mobilityArea, salary range, TJM range, pagination. Returns a paginated list of profiles. |
| `getCandidateDetail` | `CandidateDetailTool` | Retrieves the complete profile of a candidate by ID: contact details, pipeline state, contract preferences, salary/TJM expectations, mobility, recruitment metadata. Call after `searchCandidates`. |
| `getCandidateTechnicalDocument` | `CandidateTechnicalDocTool` | Retrieves the technical document (CV/skills profile) of a candidate: skills text, expertise domains, diplomas, experience level, tools with proficiency (1–5), languages with levels. Call after `getCandidateDetail` for deep skills analysis. |

**Call order enforced by descriptions:**
`getDictionary` → `searchCandidates` → `getCandidateDetail` → `getCandidateTechnicalDocument`

#### `searchCandidates` — Filter Parameters

| Parameter | Type | Description |
|---|---|---|
| `keywords` | `String` | Full-text search. Operators: `+term`, `"exact phrase"`. Covers CV, TD, name, title, email, phone. |
| `state` | `Integer` | Candidate state ID — from `getDictionary: setting.state.candidate` |
| `availabilityType` | `Integer` | Availability type ID — from `getDictionary: setting.availability`. `9` = available after date. |
| `availabilityDate` | `String` | ISO 8601 (`yyyy-MM-dd`). Used with `availabilityType = 9`. |
| `contractType` | `Integer` | Contract type ID — from `getDictionary: setting.typeOf.contract` |
| `experience` | `Integer` | Experience level ID — from `getDictionary: setting.experience` |
| `training` | `String` | Diploma level ID — from `getDictionary: setting.training` |
| `expertiseAreas` | `String` | Pipe-separated expertise area IDs. Example: `"backend\|microservices"` |
| `activityAreas` | `String` | Pipe-separated activity sector IDs. Example: `"finance\|industry"` |
| `mobilityArea` | `String` | Mobility zone ID — from `getDictionary: setting.mobilityArea` |
| `minSalary` / `maxSalary` | `Double` | Salary range filter (€/year) |
| `minTjm` / `maxTjm` | `Double` | Daily rate range filter (€/day) |
| `page` / `numberPerPage` | `Integer` | Pagination. Default: page=1, numberPerPage=25, max=100 |

All parameters are optional. Null parameters are never sent as query params to BoondManager.

---
## Implementation Rules

* Keep tools business-oriented — no CRUD naming (`find_best_candidates` OK / `getCandidateById` KO).
* No raw BoondManager API exposure through tools.
* Use `@Tool` annotations and `ToolCallbackProvider` — no custom MCP dispatcher.
* Use explicit DTOs with records where possible — no field injection.
* Constructor injection only.
* All reference data (skills, languages, contract types) must be resolved via `/application/dictionary` — no hardcoded enums.
* Use `UriComponentsBuilder` for dynamic query params — never append null values to requests.
* The MCP Server communicates directly with BoondManager APIs using WebClient.
* The Python backend consumes MCP tools instead of accessing BoondManager directly.
* Keep MCP tools deterministic and business-oriented.
* Delegate non-deterministic AI reasoning and orchestration to the Python backend.

---

## Package Structure

```
com.sijo.mcpboondmanager
├── client         ← WebClient beans (BoondManager + Python backend)
├── config         ← @ConfigurationProperties, Spring config
├── dto            ← explicit request/response records
├── exception      ← typed exceptions, global handler
├── infrastructure ← low-level HTTP adapters
├── service        ← BoondManager service layer
└── tools          ← @Tool-annotated classes
```

---

## Configuration

All external systems must be configured via `application.yml` + `@ConfigurationProperties`.

Never hardcode URLs, credentials, or ports.

---

## Testing

* Mock BoondManager HTTP responses in unit tests — never call BoondManager directly.
* Test tools independently from the transport layer.
* Test service layer with controlled WebClient mocks.
* Do not write tests that depend on a live Python backend.

---

## Acceptance Criteria

An implementation is acceptable when:

* Tools express business intent and are not CRUD wrappers.
* MCP is the only path to BoondManager data.
* All reference data is resolved dynamically via dictionary tools.
* Python backend is the only source of ranking and AI reasoning.
* Error handling is structured, typed, and user-safe.
* No hardcoded values exist for URLs, credentials, or reference data.
* Correlation IDs are propagated through all tool executions.