# MCP BoondManager Server

[![Java](https://img.shields.io/badge/Java-21-orange.svg)](https://www.oracle.com/java/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-4.x-6DB33F.svg)](https://spring.io/projects/spring-boot)
[![Spring AI](https://img.shields.io/badge/Spring%20AI-1.1.x-6DB33F.svg)](https://spring.io/projects/spring-ai)
[![Spring WebFlux](https://img.shields.io/badge/Spring-WebFlux-6DB33F.svg)](https://docs.spring.io/spring-framework/reference/web/webflux.html)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-blue.svg)](https://modelcontextprotocol.io/)

## Overview

The **MCP BoondManager Server** is a [Model Context Protocol](https://modelcontextprotocol.io/) server that acts as the **exclusive gateway between AI agents and the [BoondManager](https://www.boondmanager.com/) APIs**.

It exposes a set of deterministic, business-oriented tools dedicated to **HR and recruitment teams**. Through these tools, AI assistants can:

* Simplify candidate search.
* Accelerate sourcing workflows.
* Reduce repetitive actions.
* Improve access to recruitment information.
* Assist decision-making during recruitment processes.

Every interaction with BoondManager — authentication, query construction, DTO normalization, reference-data resolution — is encapsulated inside this server. AI agents never call BoondManager directly; they consume MCP tools.

## Architecture

The system is split into two layers with strict boundaries.

```
┌─────────────────────────────┐     ┌─────────────────────────────┐     ┌──────────────────────┐
│      Python Backend         │     │       MCP Server            │     │   BoondManager APIs  │
│   (FastAPI + LangGraph)     │     │  (Java 21 / Spring Boot)    │     │                      │
│                             │ MCP │                             │HTTPS│                      │
│  • AI orchestration         ├────►│  • MCP tool exposure        ├────►│  • /application/     │
│  • LangGraph workflows      │     │  • BoondManager abstraction │     │    dictionary        │
│  • Ranking & scoring        │◄────┤  • Streamable HTTP transport│◄────┤  • /candidates       │
│  • Reasoning / BI           │     │  • Validation & DTO mapping │     │  • /candidates/{id}/ │
│  • Conversation memory      │     │  • Correlation ID propagation│    │    information       │
│                             │     │                             │     │  • /candidates/{id}/ │
│                             │     │                             │     │    administrative    │
│                             │     │                             │     │  • /candidates/{id}/ │
│                             │     │                             │     │    technical-data    │
└─────────────────────────────┘     └─────────────────────────────┘     └──────────────────────┘
```

### The MCP Server owns

* MCP tool exposure.
* BoondManager API abstraction.
* Transport handling (Streamable HTTP).
* Request validation.
* Correlation ID propagation.
* Authentication and communication with BoondManager APIs.
* DTO normalization and query parameter construction.
* Business-oriented deterministic recruitment tools.

### The Python Backend owns

* AI orchestration.
* LangGraph workflows.
* Candidate ranking and scoring.
* Reasoning and business intelligence.
* Conversation memory and agent workflows.
* MCP tool orchestration.

### The MCP Server must NOT

* Implement autonomous AI reasoning.
* Implement LangGraph workflows or agent state machines.
* Expose raw BoondManager API endpoints.
* Contain opaque AI scoring or ranking logic.
* Use hardcoded enums for reference data (skills, contract types, etc.).

> The Python backend must **never** call BoondManager APIs directly. All BoondManager interactions go through the MCP Server.

## Available MCP Tools

Tools are designed to be called in sequence. The descriptions embedded in each `@Tool` enforce the recommended call order:

```
getDictionary → searchCandidates → getCandidateDetail → getCandidateTechnicalDocument
                                 → getCandidateAdministrative
```

| Tool | Class | Description |
|---|---|---|
| `getDictionary` | `BoondDictionaryTool` | Retrieves all BoondManager reference data: diploma levels, contract types (`setting.typeOf.contract`), resource types (`setting.typeOf.resource`), availability types, experience levels, expertise areas, activity sectors, tools, languages, candidate states. Must be called before `searchCandidates` to resolve human-readable values to their IDs. |
| `searchCandidates` | `CandidateSearchTool` | Searches candidates with a rich set of optional filters: keyword search (with `keywordsType`), candidate states/types, availability/contract/experience, expertise & activity areas, mobility, languages, tools, evaluations, sources, profile completeness (`shields`), geographic search (location/coordinates + radius), date-range filters, sorting, and response-column selection. Returns a paginated list of profiles. See the [parameters](#searchcandidates--parameters) below. |
| `getCandidateDetail` | `CandidateDetailTool` | Retrieves the detailed information profile of a candidate by ID (`GET /candidates/{id}/information`): contact details, civility, date of birth, postal address, pipeline state, resource type (`typeOf` via `setting.typeOf.resource`), availability, mobility zones, sourcing origin, global evaluation, information notes, and creation/update metadata. Call after `searchCandidates`. |
| `getCandidateAdministrative` | `CandidateAdministrativeTool` | Retrieves administrative data (`GET /candidates/{id}/administrative`): salary expectations (`currentSalary`, `minSalary`, `maxSalary`), daily rate / TJM (`currentDailyRate`, `minDailyRate`, `maxDailyRate`), currency, and — crucially — the **desired contract type** (`desiredContract`, resolves via `setting.typeOf.contract`: CDI=0, CDD=1, etc.). This is the authoritative source for `contract_preferences` displayed in candidate cards. |
| `getCandidateTechnicalDocument` | `CandidateTechnicalDocTool` | Retrieves the technical document (CV / skills profile) of a candidate (`GET /candidates/{id}/technical-data`): title, skills text, experience level, training/diploma level, diplomas, expertise domains, activity sectors, tools with proficiency level, languages with level, and summary. `id` is the candidate id, `tdId` the document id. Call after `getCandidateDetail` for deep skills analysis. |

### `searchCandidates` — Parameters

All parameters are optional. Repeatable parameters are typed as `List<…>` and serialized as multiple
`name[]=value` query parameters (BoondManager **unions** the values); null values and empty lists are
never sent.

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

| Parameter | Type | Description |
|---|---|---|
| `page` | `Integer` | Page number (1-based). Default: `1`. |
| `maxResults` | `Integer` | Results per page (1–500). Default: `30`. |
| `sort` | `List<String>` | Sort field(s): `lastName`, `firstName`, `title`, `availability`, `availabilityType`, `numberOfActivePositionings`, `mainManager.lastName`, `updateDate`, `state`, `experience`, `creationDate`, `evaluation`, `hrManager.lastName`, `source`, `distance`. |
| `order` | `String` | Sort direction: `asc` or `desc`. |
| `columns` | `List<String>` | Fields the API should include per candidate: `name`, `title`, `state`, `activePositionings`, `availability`, `mobilityAreas`, `details`, `updated`, `mainManager`, `resume`, `hrManager`, `expertiseAreas`, `creationDate`, `lastActionDate`, `source`, `diplomas`, `activityAreas`, `globalEvaluation`, `evaluations`, `experience`, `references`, `languages`, `tools`. |

## Package Structure

```
com.sijo.mcpboondmanager
├── client          ← BoondManager HTTP client wrapper (BoondManagerClient)
├── config          ← @ConfigurationProperties (BoondManagerProperties), MCP server & WebClient config
├── dto             ← explicit request/response records
│   ├── boond       ← raw BoondManager API envelopes & attributes
│   ├── candidate   ← normalized candidate / technical-document DTOs
│   ├── common      ← shared DTOs (pagination metadata)
│   └── dictionary  ← reference-data DTOs
├── exception       ← typed exceptions (Boond API, not-found, dictionary, external service)
├── infrastructure  ← low-level HTTP adapters (correlation ID filter, MDC keys)
├── service         ← BoondManager service layer
└── tools           ← @Tool-annotated classes (MCP tool exposure)
```

## Configuration

All external systems are configured through `application.yaml` and bound to typed `@ConfigurationProperties` records (e.g. `BoondManagerProperties`). **No URLs, credentials, or ports are hardcoded** — every external value is overridable via environment variables.

Minimal `application.yaml`:

```yaml
server:
  port: 8080

spring:
  application:
    name: mcp-boondmanager
  ai:
    mcp:
      server:
        name: mcp-boondmanager
        version: @project.version@
        type: SYNC
        protocol: STREAMABLE
        streamable-http:
          mcp-endpoint: /mcp

boondmanager:
  base-url: ${BOONDMANAGER_BASE_URL:https://ui.boondmanager.com/api/}
  jwt-client: ${BOONDMANAGER_JWT_CLIENT:<your-jwt-client-token>}
  timeout: ${BOONDMANAGER_TIMEOUT:15s}
  webclient:
    # Max in-memory buffer for decoding large responses (e.g. /application/dictionary).
    max-in-memory-size: ${BOONDMANAGER_MAX_IN_MEMORY_SIZE:16MB}

logging:
  pattern:
    level: "%5p [%X{correlationId:-}]"
  level:
    com.sijo.mcpboondmanager: INFO
```

| Variable | Description | Default |
|---|---|---|
| `BOONDMANAGER_BASE_URL` | Base URL of the BoondManager API. | `https://ui.boondmanager.com/api/` |
| `BOONDMANAGER_JWT_CLIENT` | JWT client token used for BoondManager authentication. | — (required) |
| `BOONDMANAGER_TIMEOUT` | HTTP timeout for BoondManager calls. | `15s` |
| `BOONDMANAGER_MAX_IN_MEMORY_SIZE` | Max in-memory buffer for response decoding. | `16MB` |

> Provide credentials through environment variables or a secrets manager. Never commit real tokens.

The MCP server exposes the **Streamable HTTP** transport on the `/mcp` endpoint.

## Getting Started

### Prerequisites

* **Java 21** (JDK 21+)
* **Maven 3.9+**
* A valid **BoondManager JWT client token**

### Build

```bash
mvn clean package
```

### Run locally

```bash
export BOONDMANAGER_JWT_CLIENT="<your-jwt-client-token>"
mvn spring-boot:run
```

The MCP endpoint is then available at `http://localhost:8080/mcp`.

To run the packaged JAR directly:

```bash
java -jar target/mcp-boondmanager-0.0.1-SNAPSHOT.jar
```

## Testing

Testing philosophy:

* **Mock BoondManager HTTP responses** in unit tests — never call BoondManager directly.
* Test tools **independently from the transport layer**.
* Test the service layer with **controlled WebClient mocks**.
* Do **not** write tests that depend on a live Python backend.

```bash
mvn test
```

## Contributing / Implementation Rules

When working in this project, follow these rules:

* **Business-oriented tools** — express business intent, no CRUD naming (`searchCandidates` ✅ / `getCandidateById` ❌ as a public tool).
* **No raw BoondManager exposure** — tools must never surface raw API endpoints.
* **`@Tool` + `ToolCallbackProvider`** — no custom MCP dispatcher or tool registry.
* **Constructor injection only** — no field injection.
* **Explicit DTOs with records** wherever possible; prefer immutable objects.
* **No hardcoded enums** — all reference data (skills, languages, contract types, states) must be resolved dynamically via `/application/dictionary`.
* **`UriComponentsBuilder` for query params** — never append null values to requests.
* **Correlation ID propagation** — propagate the correlation ID through all tool executions (see `infrastructure.CorrelationIdFilter` / `MdcKeys`).
* **Deterministic & stateless tools** — delegate all non-deterministic AI reasoning, ranking, and orchestration to the Python backend.
* **Configuration over hardcoding** — all external values via `application.yaml` + `@ConfigurationProperties`.

