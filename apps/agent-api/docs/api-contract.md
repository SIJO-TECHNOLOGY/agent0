# API Contract

## Endpoints

```text
POST /api/search
POST /api/search/stream
POST /api/chat
GET  /api/candidate-states
```

`/api/search` executes a natural-language search workflow through the Agent API
and returns a frontend-oriented response. `/api/search/stream` delegates to the
same workflow and emits sanitized Server-Sent Events style progress, including
planning, MCP tool execution, result normalization, candidate-card previews, and
bounded LLM replan decisions. `/api/chat` is the compatibility endpoint consumed
by the current web UI; it delegates to the same search workflow and returns
`{ conversation_id, message, ui, candidates }`.

The frontend never consumes raw MCP or BoondManager payloads by default.

## Search Request

```json
{
  "query": "Find Java consultants in Paris",
  "sources": ["boond", "linkedin"],
  "filters": { "candidate_states": ["7", "8"] }
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | Natural-language candidate search request. |
| `sources` | array of strings | no | Candidate sources to search: any of `"boond"`, `"linkedin"`. Empty/omitted = "no selection" (resolved server-side). May also be passed inside `filters.sources`. |
| `filters` | object | no | Optional structured filters from the UI. Defaults to an empty object. |

Supported filter keys:

| Key | Type | Description |
| --- | --- | --- |
| `candidate_states` | array of state ids | Candidate pipeline states selected in the UI (ids from `GET /api/candidate-states`). Multiple states are additive (union) and applied server-side on every search pass (`candidateStates`). See ADR-015. |
| `search_page` | integer | Session-driven provider page for "show me other profiles" follow-ups. |

### Candidate sources (multi-source)

The `sources` selection is resolved **once**, server-side, and drives
deterministic routing (the LLM planner can never override it). See ADR-017.

| Selection | Effective sources |
| --- | --- |
| `["boond"]` | BoondManager only |
| `["linkedin"]` | LinkedIn only |
| `["boond","linkedin"]` | both |
| `[]` or omitted | both when external search is enabled, else BoondManager only |

When `EXTERNAL_SEARCH_ENABLED=false`, LinkedIn is dropped from any resolved set
(never route to a disabled source). LinkedIn discovery targets **public** web
pages only (never LinkedIn Recruiter / private data).

## Chat Request

```json
{
  "message": "Find Java candidates in Paris",
  "conversation_id": "conv_123"
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `message` | string | yes, unless `interaction` is provided | User message from the chat UI. |
| `conversation_id` | string | no | Existing conversation id. A new one is created when omitted. |
| `interaction` | object | no | Structured UI interaction, such as clarification values. |
| `sources` | array of strings | no | Candidate sources for this turn (`"boond"`, `"linkedin"`). Empty/omitted = no selection. |

## Response Body

```json
{
  "conversation_id": "conv_123",
  "message": "Found 1 candidate matching your search: Sarah Martin.",
  "ui": {
    "type": "candidate_cards",
    "candidates": [
      {
        "id": "41924",
        "full_name": "Sarah Martin",
        "title": "Backend Java Engineer",
        "experience_years": 7,
        "location": "Paris, France",
        "availability": "Available immediately",
        "skills": ["Java", "Spring", "Kafka"],
        "match_score": 0.86,
        "summary": "Sarah Martin - Backend Java Engineer.",
        "boond_url": null
      }
    ]
  }
}
```

The values above are examples only. Real values must be adapted from
BoondManager MCP server results.

## Response Fields

| Field | Type | Description |
| --- | --- | --- |
| `conversation_id` | string | Stable identifier for the request/conversation. |
| `message` | string | Short user-facing reply grounded in the candidate list. |
| `ui` | object | UI block describing how the frontend should render the answer. |

### `ui` Object

| Field | Type | Description |
| --- | --- | --- |
| `type` | string | `"candidate_cards"` for candidate search responses. |
| `candidates` | array | List of candidate cards. Empty array when no candidates match. |

### Candidate Card

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable identifier for the candidate. |
| `full_name` | string \| null | Derived from name fields when present. |
| `title` | string \| null | Job title or headline if available. |
| `experience_years` | number \| null | Years of experience when available. |
| `location` | string \| null | Readable location derived from city, country, or address fields. |
| `availability` | string \| null | Readable availability label or availability date. |
| `skills` | array of strings | Empty array when unknown. |
| `match_score` | number \| null | Relevance score when available. |
| `summary` | string \| null | Short MCP-grounded summary. |
| `boond_url` | string \| null | External link when the MCP result provides one. |
| `state_label` | string \| null | Candidate pipeline-state label resolved from the dictionary (all cards, not just the enriched slice). |
| `state_id` | string \| null | Stable pipeline-state id backing `state_label`; used by the frontend's display-only state filter. |
| `sources` | array of strings | Providers this card was assembled from: `["boond"]`, `["linkedin_web"]`, or both when merged. |
| `boond_ids` | array of strings | BoondManager record id(s) behind the card (multiple when several Boond records map to one person). |
| `linkedin_url` | string \| null | Canonical public LinkedIn profile URL for external candidates. |
| `consulting_status` | string \| null | SIJO consultant qualification: `confirmed` / `probable` / `unknown` / `no` (`null` for pure Boond cards). |
| `long_mission_status` | string \| null | Long-mission (>= threshold) evidence: `confirmed` / `probable` / `unknown` / `no`. |
| `longest_mission_months` | number \| null | Longest evidenced mission duration in months, when known. |
| `external_evidence` | array | Grounded `{field, value, source_url}` items for external candidates; `[]` otherwise. |
| `public_profile_incomplete` | boolean | `true` for LinkedIn/public-web cards whose public data may be partial. |

## Normalization Rules

- Raw MCP and BoondManager payloads are not exposed to the frontend by default.
- Unknown scalar or numeric fields are `null`.
- Unknown list fields are `[]`.
- `full_name` is derived from `firstName` and `lastName` when present.
- `location` is derived from `city`, `country`, or address-style fields.
- `availability` prefers an explicit label and falls back to a date.
- `summary` may be generated by the backend, but it must be grounded in MCP data.
- `boond_url` is `null` unless the MCP record provides a safe `http(s)://` URL.

## Validation Rules

- `query` and `message` must be non-empty after trimming when provided.
- `filters` must be an object when provided.
- Unknown filter keys may be accepted for forward compatibility, but must not be blindly passed to MCP tools.
- Validation failures return structured `4xx` responses.
- Successful search responses are deterministic in shape, even when no candidates are found.

## Candidate States Endpoint

`GET /api/candidate-states` returns the candidate pipeline states the UI may
offer as search filters, sourced from the BoondManager dictionary through MCP
(`getDictionary`, TTL-cached per ADR-013):

```json
{
  "states": [
    { "id": "7", "label": "Vivier" },
    { "id": "8", "label": "A jouer" }
  ]
}
```

Excluded states ("Ne plus contacter", "A SUPPRIMER", "Proposition refusé") are
filtered out server-side and never offered; candidates in those states are also
removed from search results entirely. When the dictionary cannot be fetched the
endpoint returns the standard `mcp_client_unavailable` 503 envelope.

## Error Response Shape

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request payload failed validation.",
    "details": {}
  },
  "warnings": []
}
```

When the MCP client is unbound or unavailable, search and chat requests return a
structured 503 envelope:

```json
{
  "error": {
    "code": "mcp_client_unavailable",
    "message": "The MCP client is not initialized. The Agent API cannot serve search requests until an MCP client is bound.",
    "details": {}
  }
}
```

For successful requests with no matching candidates, prefer a `200` response:

```json
{
  "conversation_id": "conv_123",
  "message": "I could not find candidates matching your search.",
  "ui": {
    "type": "candidate_cards",
    "candidates": []
  }
}
```

## API Conventions

- FastAPI owns request validation and response serialization.
- Route handlers delegate workflow execution to services.
- The service layer adapts LangGraph and MCP output into candidate-card responses.
- Tool errors may be logged internally or surfaced as safe messages, but raw MCP errors and stack traces must not be returned to the frontend.
- Secrets must never be returned.

## Future UI Types

Other UI types may be added later, for example:

- `mission_cards`
- `client_cards`
- `table`
- `clarification_request`
- `error_message`

Do not add them to the default contract until the frontend supports them.

## Streaming Search Endpoint

`POST /api/search/stream` returns user-facing progress events for the same
search workflow used by `/api/search`.

Expected event categories include:

- `search_started`
- `tools_discovered`
- `plan_created`
- `plan_validated`
- `tool_call_started`
- `tool_call_completed`
- `results_normalized`
- `candidate_cards_partial`
- `replan_requested`
- `final_response`
- `search_failed`

When the bounded LLM reflection loop elects to replan, the stream emits
`replan_requested` with `decided_by: "llm"` and then emits the next plan
lifecycle. Streaming events must not expose raw MCP payloads, raw BoondManager
payloads, secrets, stack traces, or chain-of-thought.

## Operational API Decisions

- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) explains why liveness, readiness, and search availability are separate API concerns.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) explains why startup cancellation errors still surface as MCP-unavailable behavior instead of taking down `/api/health`.
