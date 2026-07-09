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
* Spring Boot 4.0.6 (parent)
* Spring AI 1.1.7 — MCP server via `spring-ai-starter-mcp-server-webmvc`, exposed over Streamable HTTP
* Spring WebFlux `WebClient` — outbound HTTP to the BoondManager API
* Spring Boot Validation (Jakarta Bean Validation) — config & DTO constraints
* Lombok (compile-time only)
* Build tool: Maven (Spring Boot parent). Tests: `spring-boot-starter-test`, `reactor-test`
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
| `getDictionary` | `BoondDictionaryTool` | Retrieves all BoondManager reference data: diploma levels, contract types (`setting.typeOf.contract`: CDI/CDD/Freelance/etc.), resource types (`setting.typeOf.resource`: Salarié/Portage/Freelance/etc.), availability types, experience levels, expertise areas, activity sectors, tools, languages, candidate states. Must be called before `searchCandidates` to resolve human-readable values to their IDs. |
| `searchCandidates` | `CandidateSearchTool` | Searches candidates with a rich set of optional filters: keyword search (with `keywordsType`), candidate states/types, availability/contract/experience, expertise & activity areas, mobility, languages, tools, evaluations, sources, profile completeness (`shields`), geographic search (location/coordinates + radius), date-range filters, sorting, and response-column selection. Returns a paginated list of profiles. See the parameter table below. |
| `getCandidateDetail` | `CandidateDetailTool` | Retrieves the profile from `GET /candidates/{id}/information`: contact details, civility, date of birth, postal address, pipeline state, resource type (`typeOf` resolves via `setting.typeOf.resource` — **not** the desired contract type), availability, mobility zones, sourcing origin, global evaluation, information notes, creation/update metadata. Call after `searchCandidates`. |
| `getCandidateAdministrative` | `CandidateAdministrativeTool` | Retrieves administrative data from `GET /candidates/{id}/administrative`: salary expectations, daily rate / TJM, currency, and the **desired contract type** (`desiredContract` field, resolves via `setting.typeOf.contract`). This is the **authoritative source** for `contract_preferences`. `desiredContract: -1` means not set. Call after `searchCandidates`. |
| `getCandidateTechnicalDocument` | `CandidateTechnicalDocTool` | Retrieves the technical document (CV / skills profile) from `GET /candidates/{id}/technical-data`: title, skills text, experience level, training/diploma level, diplomas, expertise domains, activity sectors, tools with proficiency level, languages with level, and summary. The `id` field is the candidate id and `tdId` is the technical-document id. Call after `getCandidateDetail` for deep skills analysis. |

**Call order enforced by descriptions:**
`getDictionary` → `searchCandidates` → `getCandidateDetail` → `getCandidateTechnicalDocument`
                                     → `getCandidateAdministrative`

**Important field disambiguation:**
- `typeOf` in `getCandidateDetail` (`/information`) → **resource type** → resolves via `setting.typeOf.resource`
- `desiredContract` in `getCandidateAdministrative` (`/administrative`) → **desired contract type** → resolves via `setting.typeOf.contract`

#### `searchCandidates` — Parameters

All parameters are optional. Repeatable parameters are typed as `List<…>` and serialized as multiple
`name[]=value` query params (BoondManager **unions** the values); null values and empty lists are never
sent.

**Keyword search**

| Parameter | Type | Description |
|---|---|---|
| `keywords` | `String` | Full-text query. Operators: `+term`, `"exact phrase"`. The field searched is set by `keywordsType`. |
| `keywordsType` | `String` | Field targeted by `keywords`: `resumeTd` (default), `lastName`, `firstName`, `fullName`, `strictFullName`, `emails`, `title`, `titleSkills`, `phones`, `resume`, `td`. |

**Reference filters** (repeatable, values unioned)

| Parameter | Type | Dictionary key |
|---|---|---|
| `candidateStates` | `List<Integer>` | `setting.state.candidate` |
| `candidateTypes` | `List<Integer>` | `setting.typeOf.resource` |
| `availabilityTypes` | `List<Integer>` | `setting.availability` |
| `contractTypes` | `List<Integer>` | `setting.typeOf.contract` |
| `experiences` | `List<Integer>` | `setting.experience` |
| `expertiseAreas` | `List<String>` | `setting.expertiseArea` |
| `activityAreas` | `List<String>` | nested option IDs under `setting.activityArea[].option` |
| `mobilityAreas` | `String` | nested option ID under `setting.mobilityArea[].option` |
| `languages` | `List<String>` | `"<spokenId>\|<levelId>"` from `setting.languageSpoken` + `setting.languageLevel` |
| `tools` | `List<String>` | `setting.tool`. Add `"#AND#"` as the first element to require ALL listed tools |
| `evaluations` | `List<String>` | `setting.evaluation` |
| `sources` | `List<String>` | `setting.source` |
| `shields` | `List<String>` | profile completeness: `uncomplete`, `minimum`, `complete` |

**Geographic search**

| Parameter | Type | Description |
|---|---|---|
| `location` | `String` | Free-text address to geocode (e.g. `"Paris"`). Requires `geoDistance`. |
| `coordinates` | `String` | `"latitude,longitude"` (e.g. `"48.8566,2.3522"`). Requires `geoDistance`. |
| `geoDistance` | `Integer` | Search radius in km (5–200). Required with `location`/`coordinates`. |

**Date filters**

| Parameter | Type | Description |
|---|---|---|
| `period` | `String` | Date field to filter: `created`, `available`, `updated`, `noAction`, `withActions`. |
| `startDate` | `String` | ISO date `yyyy-MM-dd`. Used with `period`. |
| `endDate` | `String` | ISO date `yyyy-MM-dd`. Used with `period`. |
| `periodDynamic` | `String` | Relative preset instead of start/end, e.g. `thisMonth`, `lastMonth`, `nextMonth`, `thisYear`. |

**Pagination, sorting & response shaping**

| Parameter | Type | Description                                                                                                                                                                                                                                                                                                                                                               |
|---|---|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `page` | `Integer` | Page number (1-based). Default: `1`.                                                                                                                                                                                                                                                                                                                                      |
| `maxResults` | `Integer` | Results per page (1–100). Default: `30`.                                                                                                                                                                                                                                                                                                                                  |
| `sort` | `List<String>` | Sort field(s): `lastName`, `firstName`, `title`, `availability`, `availabilityType`, `numberOfActivePositionings`, `mainManager.lastName`, `updateDate`, `state`, `experience`, `creationDate`, `evaluation`, `hrManager.lastName`, `source`, `distance`.                                                                                                                 |
| `order` | `String` | Sort direction: `asc` or `desc`.                                                                                                                                                                                                                                                                                                                                          |
| `columns` | `List<String>` | Fields the API should include per candidate: `name`, `title`, `state`, `activePositionings`, `availability`, `mobilityAreas`, `details`, `updated`, `mainManager`, `resume`, `hrManager`, `expertiseAreas`, `creationDate`, `lastActionDate`, `source`, `diplomas`, `activityAreas`, `globalEvaluation`, `evaluations`, `experience`, `references`, `languages`, `tools`. |

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
├── client         ← BoondManager HTTP client wrapper (BoondManagerClient)
├── config         ← @ConfigurationProperties (BoondManagerProperties), WebClient & MCP server config
├── dto            ← explicit request/response records
│   ├── boond      ← raw BoondManager API envelopes & attributes
│   ├── candidate  ← normalized candidate / technical-document DTOs
│   ├── common     ← shared DTOs (pagination metadata)
│   └── dictionary ← reference-data DTOs
├── exception      ← typed exceptions (Boond API, candidate-not-found, dictionary, external service)
├── infrastructure ← low-level HTTP adapters (correlation ID filter, MDC keys)
├── service        ← BoondManager service layer
└── tools          ← @Tool-annotated classes (MCP tool exposure)
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