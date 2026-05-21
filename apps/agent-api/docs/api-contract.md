# API Contract

## Endpoint

```text
POST /api/search
```

Executes a natural-language search workflow through the Agent API.

## Request Body

```json
{
  "query": "Find senior Java consultants available next month",
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
  "original_query": "Find senior Java consultants available next month",
  "interpreted_intent": {},
  "execution_plan": [],
  "tool_calls": [],
  "results": [],
  "summary": "Summary of the best matching results.",
  "confidence": 0.92,
  "warnings": []
}
```

## Response Fields

| Field | Type | Description |
| --- | --- | --- |
| `original_query` | string | Original user query. |
| `interpreted_intent` | object | Structured interpretation of user intent. |
| `execution_plan` | array | Plan steps used by the LangGraph workflow. |
| `tool_calls` | array | Sanitized MCP tool call records. |
| `results` | array | Aggregated and ranked results from MCP tools. |
| `summary` | string | AI-generated user-facing summary. |
| `confidence` | number | Confidence score from `0.0` to `1.0`. |
| `warnings` | array | User-safe warnings about ambiguity, partial results, or degraded execution. |

## Validation Rules

- `query` must be non-empty after trimming.
- `filters` must be an object when provided.
- Unknown filter keys may be accepted for forward compatibility but should not be blindly passed to MCP tools.
- Validation failures should return structured `4xx` responses.

## Error Response Shape

Use a stable error envelope for API-level failures.

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The search query is required.",
    "details": {}
  },
  "warnings": []
}
```

## API Conventions

- FastAPI owns request validation and response serialization only.
- Route handlers should delegate workflow execution to services.
- Responses should be deterministic in shape even when results are empty.
- Tool errors should appear as warnings when partial results can still be returned.
- Secrets, raw MCP errors, and provider stack traces must not be returned.

## Future Streaming Compatibility

The MVP response is synchronous JSON.

Design internal workflow events so future SSE or WebSocket support can stream:

- Intent interpretation.
- Plan creation.
- Tool call progress.
- Partial result counts.
- Final summary.

## Operational API Decisions

- [ADR-003 - Graceful MCP Degradation And Health Strategy](../../../docs/decisions/adr-003-graceful-mcp-degradation-and-health-strategy.md) explains why liveness, readiness, and search availability are separate API concerns.
- [ADR-004 - asyncio.CancelledError Escapes Graceful MCP Degradation](../../../docs/decisions/adr-004-asyncio-cancelled-error-mcp-startup.md) explains why startup cancellation errors still surface as MCP-unavailable behavior instead of taking down `/api/health`.
