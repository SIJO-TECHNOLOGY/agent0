# SIJO Assistant API Contract (Frontend → Backend)

This document describes what the frontend expects from the backend. Any structural, naming, or HTTP-status mismatch can cause visible issues in the interface.

---

## Base Configuration

| Setting | Current development value |
|---|---|
| Base URL | `http://localhost:8000` |
| Format | JSON (`Content-Type: application/json`) |
| Auth | Microsoft MSAL bearer token in the `Authorization` header |
| Chat timeout | 60 seconds. After that, a timeout error is shown to the user. |

In production, the base URL and MSAL settings (`clientId`, `tenantId`, `redirectUri`) must be configured in `config.js` and `msalConfig.js`.

---

## Expected Endpoints

### `GET /api/health`

Checks whether the backend is reachable when the app starts.

Expected response (`200`):

```json
{ "status": "ok" }
```

---

### `GET /api/conversations`

Loads the authenticated user’s conversation list for the sidebar.

Expected response (`200`):

```json
[
  {
    "id": "string",
    "title": "string",
    "created_at": "ISO 8601",
    "updated_at": "ISO 8601"
  }
]
```

Return `[]` when there are no conversations. Do not return `null`.

---

### `POST /api/conversations`

Creates a new conversation.

Request body:

```json
{ "title": "Nouvelle conversation" }
```

Expected response (`200` or `201`):

```json
{
  "id": "string",
  "title": "string",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601"
}
```

---

### `GET /api/conversations/:id`

Loads an existing conversation and its message history.

Expected response (`200`):

```json
{
  "id": "string",
  "title": "string",
  "messages": [
    {
      "role": "user",
      "content": "string"
    },
    {
      "role": "assistant",
      "content": "string"
    }
  ]
}
```

`messages` may be `[]`, but the field must be present.

---

### `DELETE /api/conversations/:id`

Deletes a conversation.

Expected response: `204 No Content`.

The response body must be empty. The frontend treats `204` as a successful response without parsing JSON.

---

### `POST /api/chat`

Main endpoint. It covers two use cases:

- sending a regular user message
- submitting a clarification form

#### Case 1 — Regular User Message

Request body:

```json
{
  "message": "string",
  "conversation_id": "string | null"
}
```

`conversation_id` is `null` when this is the first message of a conversation that has not been created yet.

#### Case 2 — Clarification Form Submission

Request body:

```json
{
  "message": null,
  "conversation_id": "string | null",
  "interaction": {
    "type": "clarification",
    "action": "submit",
    "values": {
      "field_name": "value entered by the user"
    },
    "source_ui": {
      "type": "clarification"
    }
  }
}
```

`source_ui` is the `ui` object returned by the response that triggered the clarification form.

#### Expected Response (`200`) — Common Structure

```json
{
  "conversation_id": "string",
  "message": "string",
  "ui": {
    "type": "text"
  }
}
```

The `ui` field should be present. It controls what the frontend renders after the text message.

| `ui.type` | Frontend behavior | Required extra fields |
|---|---|---|
| `text` | Displays only the text message | none |
| `candidate_cards` | Displays candidate cards below the message | `ui.candidates` or root `candidates` as a non-empty array |
| `clarification` | Displays an interactive clarification form | `ui.title` optional, `ui.questions` required |
| `candidate_detail` | Displays a detailed candidate profile | `ui.candidate` |
| `technical_summary` | Displays a structured technical analysis | `ui.title`, `ui.summary`, `ui.strengths`, `ui.weaknesses`, `ui.languages`, `ui.tools` |
| `error` | Displays the message in an error bubble | none |
| `loading` | Transitional UI state. The backend should normally not return this. | none |

If `ui` is missing or `null`, the frontend infers:

- `candidate_cards` when root `candidates` is a non-empty array
- `text` otherwise

Explicit `ui` is strongly recommended.

Strict validation rule: if `message` is empty, candidates are empty, `ui.candidate` is absent, and `ui.type` is not `technical_summary` or `loading`, the frontend treats the response as malformed.

---

## Candidate Cards

Candidate cards can be provided in two places. The frontend prioritizes `ui.candidates`.

Preferred format:

```json
{
  "conversation_id": "conv_123",
  "message": "I found 3 candidates.",
  "ui": {
    "type": "candidate_cards",
    "candidates": [
      {
        "id": "candidate_1",
        "full_name": "Sarah Martin",
        "title": "Backend Java Engineer",
        "experience_years": 7,
        "location": "Paris",
        "availability": "Available immediately",
        "skills": ["Java", "Spring", "Kafka"],
        "match_score": 0.86,
        "summary": "Confirmed backend profile.",
        "boond_url": "https://ui.boondmanager.com/"
      }
    ]
  }
}
```

Legacy fallback:

```json
{
  "conversation_id": "conv_123",
  "answer": "I found 3 candidates.",
  "candidates": [
    {
      "id": "candidate_1",
      "full_name": "Sarah Martin"
    }
  ]
}
```

Both are valid. When `ui.candidates` is present, root `candidates` is ignored.

---

## Clarification

Used when the backend needs more information before searching.

Response:

```json
{
  "conversation_id": "conv_123",
  "message": "Can you specify the location or desired experience level?",
  "ui": {
    "type": "clarification",
    "title": "Clarification needed",
    "questions": [
      {
        "field": "location",
        "label": "Desired location",
        "required": false
      },
      {
        "field": "experience",
        "label": "Experience level",
        "required": false
      }
    ]
  }
}
```

Question fields:

| Field | Type | Notes |
|---|---|---|
| `field` | string | Used as the key in submitted `values` |
| `label` | string | Label displayed to the user |
| `required` | boolean | Marks the input as required when `true` |

---

## Candidate Detail

Used when the backend returns a detailed candidate profile.

```json
{
  "conversation_id": "conv_123",
  "message": "Here is the candidate detail.",
  "ui": {
    "type": "candidate_detail",
    "candidate": {
      "id": "candidate_1",
      "full_name": "Sarah Martin",
      "title": "Backend Java Engineer",
      "experience_years": 7,
      "location": "Paris",
      "availability": "Available immediately",
      "skills": ["Java", "Spring Boot"],
      "match_score": 0.86,
      "summary": "Confirmed backend profile.",
      "boond_url": "https://ui.boondmanager.com/",
      "contract_preferences": ["CDI", "Freelance"],
      "salary_expectation": "55k€",
      "tjm": "600€"
    }
  }
}
```

`contract_preferences`, `salary_expectation`, and `tjm` are optional fields used only by the candidate detail view.

---

## Technical Summary

Used when the backend returns a technical candidate analysis.

```json
{
  "conversation_id": "conv_123",
  "message": "Here is the technical analysis.",
  "ui": {
    "type": "technical_summary",
    "title": "Technical analysis — Sarah Martin",
    "summary": "Strong Java/Spring profile with microservices experience.",
    "strengths": ["Advanced Java", "Microservices architecture"],
    "weaknesses": ["Limited frontend experience"],
    "languages": ["Fluent French", "Professional English"],
    "tools": [
      { "name": "Java", "level": 5 },
      { "name": "Spring Boot", "level": 4 }
    ]
  }
}
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `title` | string | Analysis heading |
| `summary` | string | Free narrative summary |
| `strengths` | string[] | Strengths |
| `weaknesses` | string[] | Watch points |
| `languages` | string[] | Language skills |
| `tools` | `{ name: string, level: number }[]` | Skill/tool levels, usually from 1 to 5 |

`technical_summary` responses are valid even when `message` is empty.

---

## Candidate Detail Endpoint

### `GET /api/candidates/:id`

Loads a candidate detail.

Expected response (`200`): same shape as the standard candidate object.

This endpoint exists in the frontend API layer but is not currently used by the UI. Candidate data is currently carried by `/api/chat` responses.

---

## Standard Candidate Object

Used in `ui.candidates`, root `candidates`, and `/api/candidates/:id`.

```json
{
  "id": "string",
  "full_name": "string",
  "title": "string",
  "experience_years": 5,
  "location": "string",
  "availability": "string",
  "skills": ["Java", "Spring Boot"],
  "match_score": 0.86,
  "summary": "string",
  "boond_url": "https://ui.boondmanager.com/"
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique identifier |
| `full_name` | string | Displayed as card and drawer title |
| `title` | string | Candidate role/title |
| `experience_years` | number | Displayed as years |
| `location` | string | City, region, or remote information |
| `availability` | string | Free text |
| `skills` | string[] | The UI displays at most 5 skills |
| `match_score` | number | Float from 0 to 1, displayed as a percentage |
| `summary` | string | Short profile summary |
| `boond_url` | string \| null | When missing, the BoondManager button is hidden |

---

## Expected HTTP Behavior

| Situation | HTTP status |
|---|---|
| Successful response with JSON body | `200` |
| Successful creation | `200` or `201` |
| Successful deletion without body | `204` |
| Generic error | `4xx` or `5xx` |

The frontend does not currently differentiate backend error codes. Any non-2xx response triggers the generic backend error message. `204` is the only no-body success case handled explicitly.

---

## Authentication

The frontend sends a Microsoft bearer token with backend requests:

```http
Authorization: Bearer <access_token>
```

The backend must validate the token against Microsoft. In `DEV_MODE = true`, the frontend uses a mock token (`dev-token`), which the backend may ignore for local development.

---

## Optional Debug Field

The frontend logs this field in the console when `DEV_MODE = true`.

```json
{
  "debug": {
    "intent": "candidate_search",
    "filters": { "skills": ["Java"] },
    "response_time_ms": 180
  }
}
```

Debug fields are never displayed to the user.

---

## Important Notes

- Dates must use ISO 8601 format (`created_at`, `updated_at`).
- `/api/chat` responses should always return `conversation_id`.
- The frontend does not send full history. The backend owns conversation state.
- Raw JSON must never be displayed to the user.
- Malformed JSON triggers a `malformed_response` frontend error.
- `message` is preferred over `answer`; `answer` exists only for legacy compatibility.
- The frontend does not know or call MCP tools.
- The frontend does not call OpenAI directly.
- The frontend does not call BoondManager APIs directly.
