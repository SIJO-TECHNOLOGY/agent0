# API Contract

## Endpoints

```text
POST /api/search
POST /api/search/stream
POST /api/chat
```

`/api/search` executes a natural-language search workflow through the Agent API
and returns a frontend-oriented response. `/api/search/stream` is the preferred
web UI endpoint: it runs the same workflow and streams sanitized SSE progress
events before a final `final_response` event. `/api/chat` remains a compatibility
endpoint for legacy chat-style calls and clarification interactions.

The frontend never consumes raw MCP or BoondManager payloads by default.

## Search Request

```json
{
  "query": "Find Java candidates in Paris",
  "filters": {}
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | Natural-language candidate search request. |
| `filters` | object | no | Optional structured filters from the UI. Defaults to an empty object. |

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

## Response Body

```json
{
  "conversation_id": "conv_123",
  "message": "J'ai trouvé un profil proche de votre recherche : Sarah Martin. Certains points restent à confirmer dans le dossier candidat.",
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
        "summary": "Backend Java engineer with 7 years of experience in Spring APIs, Kafka integrations, and production support for banking platforms.",
        "boond_url": "https://ui.boondmanager.com/candidates/41924/overview",
        "state_label": "Vivier",
        "mobility": "Paris (75)",
        "contract_preferences": ["CDI"],
        "technical_summary": "Solid Java/Spring backend profile.",
        "diplomas": ["Bac+5"],
        "expertise_areas": ["Banque"],
        "activity_areas": ["Business Analyst"],
        "tools": [{ "name": "SQL", "level": 1 }],
        "languages": [{ "language": "Anglais", "level": "Courant" }]
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
| `experience_label` | string \| null | Human-readable experience level resolved from the dictionary when available. |
| `location` | string \| null | Readable location derived from city, country, or address fields. |
| `availability` | string \| null | Readable availability label or availability date. |
| `skills` | array of strings | Empty array when unknown. |
| `match_score` | number \| null | Relevance score when available. |
| `summary` | string \| null | Short backend-generated summary grounded in MCP data. When a readable CV is available, the Agent API may analyze the parsed CV text with the configured LLM and return a complete, natural sentence. |
| `boond_url` | string \| null | External link when the MCP result provides one. |
| `highlights` | array of strings | Keywords or criteria highlighted by the backend. |
| `experiences` | array of objects | Recent experiences when available. |
| `ai_evaluation` | object \| null | Optional grounded match explanation. |
| `contract_preferences` | array of strings | Contract labels resolved from source data when available. |
| `salary_expectation` | string \| null | Salary expectation when available. |
| `tjm` | string \| null | Daily rate when available. |
| `mobility` | string \| null | Mobility label or readable mobility area list. |
| `strengths` | array of strings | Grounded strengths when available. |
| `watch_points` | array of strings | Grounded watch points when available. |
| `state_label` | string \| null | Candidate pipeline state label resolved from the dictionary. |
| `source` | string \| null | Candidate sourcing origin/detail when available. |
| `last_update` | string \| null | Last update date when available. |
| `technical_summary` | string \| null | Technical-document summary or, when absent, backend-generated CV summary. |
| `diplomas` | array of strings | Diplomas/training entries. |
| `expertise_areas` | array of strings | Expertise area labels. |
| `activity_areas` | array of strings | Activity area labels. |
| `tools` | array of objects | Tool or technology entries, optionally with `level`. |
| `languages` | array of objects | Language entries, optionally with `level`. |

## Normalization Rules

- Raw MCP and BoondManager payloads are not exposed to the frontend by default.
- Unknown scalar or numeric fields are `null`.
- Unknown list fields are `[]`.
- `full_name` is derived from `firstName` and `lastName` when present.
- `location` is derived from `city`, `country`, or address-style fields.
- `availability` prefers an explicit label and falls back to a date.
- BoondManager dictionary IDs should be resolved before display whenever possible
  (availability, experience, state, mobility, tools, languages, activity areas).
- Raw BoondManager experience level IDs must not be exposed as literal years.
- `summary` may be generated by the Agent API LLM layer, but it must be grounded
  in MCP data. For CV-based summaries, the MCP server only downloads/extracts
  the CV; the Agent API owns the interpretation and natural-language synthesis.
- CV summaries should be complete sentences, not raw clipped CV fragments.
- `boond_url` is either a safe `http(s)://` value from the MCP record or a
  backend-constructed BoondManager candidate overview URL based on the candidate id.
- User-facing messages should remain natural and honest. When some criteria are
  only partially confirmed, prefer wording such as "profils proches" and
  "points à confirmer" over technical warning text.

## Validation Rules

- `query` and `message` must be non-empty after trimming when provided.
- `filters` must be an object when provided.
- Unknown filter keys may be accepted for forward compatibility, but must not be blindly passed to MCP tools.
- Validation failures return structured `4xx` responses.
- Successful search responses are deterministic in shape, even when no candidates are found.

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
  "message": "Aucun candidat ne correspond à votre recherche.",
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

## Streaming Compatibility

`POST /api/search/stream` emits Server-Sent Events. Normal traffic should use
sanitized Agent API events, not MCP transport frames. A successful stream ends
with exactly one `final_response` event whose payload matches the response body
shape above. Current event categories include:

- Intent interpretation.
- Plan creation.
- Tool call progress.
- Partial candidate-card emission.
- Final summary.

## Operational API Decisions

- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) explains why liveness, readiness, and search availability are separate API concerns.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) explains why startup cancellation errors still surface as MCP-unavailable behavior instead of taking down `/api/health`.
