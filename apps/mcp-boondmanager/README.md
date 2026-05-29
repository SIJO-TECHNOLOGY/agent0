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
┌────────────────────────────┐     ┌─────────────────────────────┐     ┌──────────────────────┐
│      Python Backend         │     │       MCP Server            │     │   BoondManager APIs  │
│   (FastAPI + LangGraph)     │     │  (Java 21 / Spring Boot)    │     │                      │
│                             │ MCP │                             │HTTPS│                      │
│  • AI orchestration         ├────►│  • MCP tool exposure        ├────►│  • /candidates       │
│  • LangGraph workflows      │     │  • BoondManager abstraction │     │  • /candidates/{id}  │
│  • Ranking & scoring        │◄────┤  • Streamable HTTP transport│◄────┤  • /application/...  │
│  • Reasoning / BI           │     │  • Validation & DTO mapping │     │    dictionary        │
│  • Conversation memory      │     │  • Correlation ID propagation│    │                      │
└────────────────────────────┘     └─────────────────────────────┘     └──────────────────────┘
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
```

| Tool | Class | Description |
|---|---|---|
| `getDictionary` | `BoondDictionaryTool` | Retrieves all BoondManager reference data (diploma levels, contract types, availability types, experience levels, expertise areas, activity sectors, tools, languages, candidate states). Must be called before `searchCandidates` to resolve human-readable values to their IDs. |
| `searchCandidates` | `CandidateSearchTool` | Searches candidates with optional filters (keywords, state, availability, contract, experience, training, expertise/activity areas, mobility, salary/TJM ranges, pagination). Returns a paginated list of profiles. |
| `getCandidateDetail` | `CandidateDetailTool` | Retrieves the complete profile of a candidate by ID: contact details, pipeline state, contract preferences, salary/TJM expectations, mobility, recruitment metadata. Call after `searchCandidates`. |
| `getCandidateTechnicalDocument` | `CandidateTechnicalDocTool` | Retrieves the technical document (CV / skills profile) of a candidate: skills text, expertise domains, diplomas, experience level, tools with proficiency (1–5), languages with levels. Call after `getCandidateDetail` for deep skills analysis. |

### `searchCandidates` — Filter Parameters

All parameters are optional. Null parameters are never sent as query parameters to BoondManager.

| Parameter | Type | Description |
|---|---|---|
| `keywords` | `String` | Full-text search. Operators: `+term`, `"exact phrase"`. Covers CV, TD, name, title, email, phone. |
| `state` | `Integer` | Candidate state ID — from `getDictionary: setting.state.candidate`. |
| `availabilityType` | `Integer` | Availability type ID — from `getDictionary: setting.availability`. `9` = available after date. |
| `availabilityDate` | `String` | ISO 8601 (`yyyy-MM-dd`). Used with `availabilityType = 9`. |
| `contractType` | `Integer` | Contract type ID — from `getDictionary: setting.typeOf.contract`. |
| `experience` | `Integer` | Experience level ID — from `getDictionary: setting.experience`. |
| `training` | `String` | Diploma level ID — from `getDictionary: setting.training`. |
| `expertiseAreas` | `String` | Pipe-separated expertise area IDs. Example: `"backend\|microservices"`. |
| `activityAreas` | `String` | Pipe-separated activity sector IDs. Example: `"finance\|industry"`. |
| `mobilityArea` | `String` | Mobility zone ID — from `getDictionary: setting.mobilityArea`. |
| `minSalary` / `maxSalary` | `Double` | Salary range filter (€/year). |
| `minTjm` / `maxTjm` | `Double` | Daily rate range filter (€/day). |
| `page` / `numberPerPage` | `Integer` | Pagination. Default: `page=1`, `numberPerPage=25`, `max=100`. |

## Package Structure

```
com.sijo.mcpboondmanager
├── client          ← WebClient beans (BoondManager + Python backend)
├── config          ← @ConfigurationProperties, MCP server & WebClient config
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
* **Maven** (or the bundled Maven Wrapper)
* A valid **BoondManager JWT client token**

### Build

```bash
./mvnw clean package
```

### Run locally

```bash
export BOONDMANAGER_JWT_CLIENT="<your-jwt-client-token>"
./mvnw spring-boot:run
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
./mvnw test
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
```

