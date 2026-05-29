# API Contract

## Endpoint

```text
POST /api/search
```

Executes a natural-language search workflow through the Agent API and
returns a frontend-oriented response. The frontend never sees raw MCP
or BoondManager payloads.

## Request Body

```json
{
  "query": "Find the candidate information with candidate id 41924",
  "filters": {}
}
```

## Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | Natural-language search request. |
| `filters` | object | no | Optional structured filters from the UI. Defaults to an empty object. |

## Response Body

```json
{
  "conversation_id": "conv_1ac0fe6cade44a688bad5658f44e3971",
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
        "match_score": null,
        "summary": "Sarah Martin — Backend Java Engineer.",
        "boond_url": null
      }
    ]
  }
}
```

## Response Fields

| Field | Type | Description |
| --- | --- | --- |
| `conversation_id` | string | Stable identifier for the request/conversation. |
| `message` | string | Short user-facing reply grounded in the candidate list. |
| `ui` | object | UI block describing how the frontend should render the answer. |

### `ui` object

| Field | Type | Description |
| --- | --- | --- |
| `type` | string | Always `"candidate_cards"` for now. |
| `candidates` | array | List of candidate cards. Empty array when no candidates match. |

### Candidate card

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable identifier for the candidate. |
| `full_name` | string \| null | Derived from name fields when present. |
| `title` | string \| null | Job title / headline if available. |
| `experience_years` | number \| null | Years of experience when available. |
| `location` | string \| null | Readable location derived from city/country/address. |
| `availability` | string \| null | Readable availability label or "Available from <date>". |
| `skills` | array of strings | Empty array when unknown. |
| `match_score` | number \| null | Relevance score (search tools only). `null` for detail lookups. |
| `summary` | string \| null | Short, MCP-grounded summary. |
| `boond_url` | string \| null | External link when the MCP result provides one. |

## Normalization Rules

- Raw MCP and BoondManager payloads are never exposed to the frontend.
- Unknown scalar/numeric fields are `null`.
- Unknown list fields are `[]`.
- `full_name` is derived from `firstName`/`lastName` when present, or from
  a single available name part.
- `location` is derived from `city`/`country`/`address`-style fields.
- `availability` prefers an explicit label and falls back to an
  availability date.
- `match_score` is only surfaced for search-style tools (e.g.
  `searchCandidates`). Detail-style tools (e.g. `getCandidateDetail`)
  emit `null`.
- `boond_url` is `null` unless the MCP record provides an `http(s)://` URL.

## Validation Rules

- `query` must be non-empty after trimming.
- `filters` must be an object when provided.
- Validation failures return structured `4xx` responses (see error envelope below).

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

When the MCP client is unbound (startup failure or real MCP server
unreachable), `/api/search` returns the structured 503 envelope:

```json
{
  "error": {
    "code": "mcp_client_unavailable",
    "message": "The MCP client is not initialized. The Agent API cannot serve search requests until an MCP client is bound.",
    "details": {}
  },
  "warnings": []
}
```

## API Conventions

- FastAPI owns request validation and response serialization only.
- The service layer adapts orchestration output (LangGraph + MCP tools)
  into the candidate-card response shape.
- Responses are deterministic in shape even when no candidates match
  (empty `candidates` list).
- Secrets, raw MCP errors, and provider stack traces must not be returned.

## Future Streaming Compatibility

The MVP response is synchronous JSON.

Design internal workflow events so future SSE or WebSocket support can stream:

- Intent interpretation.
- Plan creation.
- Tool call progress.
- Partial candidate-card emission.
- Final summary.

## Operational API Decisions

- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) explains why liveness, readiness, and search availability are separate API concerns.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) explains why startup cancellation errors still surface as MCP-unavailable behavior instead of taking down `/api/health`.
