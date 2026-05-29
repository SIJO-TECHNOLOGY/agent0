# SIJO Assistant API Contract (Frontend to Backend)

This document describes what the frontend expects from the backend. The
frontend remains candidate-search focused and renders only normalized REST
responses.

## Base Configuration

| Setting | Current development value |
|---|---|
| Base URL | `http://localhost:8000` |
| Format | JSON (`Content-Type: application/json`) |
| Auth | Microsoft MSAL bearer token in the `Authorization` header |
| Chat timeout | 15 seconds for `/api/chat` |

## Endpoints

### `GET /api/health`

Expected response:

```json
{ "status": "ok" }
```

### `GET /api/conversations`

Returns the authenticated user's conversation list.

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

Return `[]` when there are no conversations.

### `POST /api/conversations`

Creates a new conversation.

```json
{ "title": "Nouvelle conversation" }
```

### `GET /api/conversations/:id`

Loads an existing conversation.

```json
{
  "id": "string",
  "title": "string",
  "messages": [
    { "role": "user", "content": "string" },
    { "role": "assistant", "content": "string" }
  ]
}
```

### `DELETE /api/conversations/:id`

Expected response: `204 No Content`.

### `POST /api/chat`

Main candidate-search endpoint.

Request:

```json
{
  "message": "Find a senior Java developer in Paris",
  "conversation_id": "conv_123"
}
```

The frontend does not send full conversation history. The backend owns
conversation state.

Clarification submission:

```json
{
  "message": null,
  "conversation_id": "conv_123",
  "interaction": {
    "type": "clarification",
    "action": "submit",
    "values": {
      "location": "Paris"
    },
    "source_ui": {
      "type": "clarification"
    }
  }
}
```

## Response Envelope

Preferred response:

```json
{
  "conversation_id": "conv_123",
  "message": "I found candidates matching your search.",
  "ui": {
    "type": "candidate_cards"
  }
}
```

Legacy response remains supported:

```json
{
  "conversation_id": "conv_123",
  "answer": "I found candidates matching your search.",
  "candidates": []
}
```

## Supported UI Types

| `ui.type` | Frontend behavior |
|---|---|
| `text` | Displays only the assistant message. |
| `candidate_cards` | Displays sourcing-oriented candidate cards. |
| `clarification` | Displays an inline clarification form. |
| `candidate_detail` | Displays a candidate-specific detail card. |
| `technical_summary` | Displays a candidate technical analysis card. |
| `error` | Displays an error bubble. |
| `loading` | Transitional state. The backend should normally not return this. |

Unsupported UI types are treated as malformed responses.

## Candidate Cards

Preferred response:

```json
{
  "conversation_id": "conv_123",
  "message": "I found 5 candidates matching your search.",
  "ui": {
    "type": "candidate_cards",
    "title": "278 relevant profiles found",
    "subtitle": "7 profiles available immediately",
    "filters_summary": ["Java", "Senior", "Paris", "Finance"],
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
        "boond_url": "https://ui.boondmanager.com/",
        "contract_preferences": ["CDI", "Freelance"],
        "salary_expectation": "55k",
        "tjm": "600",
        "mobility": "Paris and hybrid",
        "ai_evaluation": {
          "label": "AI evaluation",
          "score_label": "Ideal match - 92%",
          "reasons": [
            "Java/Spring experience matches the need",
            "Recent banking sector experience",
            "Available quickly"
          ]
        },
        "experiences": [
          {
            "title": "Senior Java Software Engineer",
            "company": "EY",
            "period": "May 2023 - present"
          }
        ],
        "highlights": ["Java", "Spring Boot", "Euronext"],
        "strengths": ["Strong Java/Spring alignment"],
        "watch_points": ["Availability should be confirmed"],
        "technical_summary": "Solid Java/Spring backend profile."
      }
    ]
  }
}
```

`ui.title`, `ui.subtitle`, and `ui.filters_summary` are optional and displayed
above the cards when present.

## Candidate Object

| Field | Type | Notes |
|---|---|---|
| `id` | string | Candidate identifier. |
| `full_name` | string | Displayed as card and drawer title. |
| `title` | string | Candidate title or target role. |
| `experience_years` | number \| null | Displayed as years when known. |
| `location` | string \| null | Candidate location or remote information. |
| `availability` | string \| null | Free text availability. |
| `skills` | string[] | Displayed as skill tags. |
| `match_score` | number \| null | Float from `0` to `1`, displayed as a percentage. |
| `summary` | string \| null | Candidate summary. |
| `boond_url` | string \| null | Opens BoondManager in a new tab when present. |
| `contract_preferences` | string[] | Optional contract preferences. |
| `salary_expectation` | string \| null | Optional salary expectation. |
| `tjm` | string \| null | Optional daily rate. |
| `mobility` | string \| null | Optional mobility or remote preference. |
| `ai_evaluation` | object \| null | Optional AI match explanation block. |
| `match_explanation` | object \| null | Alternative name for `ai_evaluation`. |
| `experiences` | object[] | Optional recent experiences. Cards display up to 3. |
| `highlights` | string[] | Optional keywords displayed as highlight tags. |
| `strengths` | string[] | Optional detected strengths. |
| `strong_points` | string[] | Alternative name for strengths. |
| `watch_points` | string[] | Optional watch points. |
| `weaknesses` | string[] | Alternative name for watch points. |
| `vigilance_points` | string[] | Alternative name for watch points. |
| `technical_summary` | string \| null | Optional technical note shown in the drawer. |

All enriched fields are optional. The frontend must remain stable when they are
absent.

## AI Evaluation Object

```json
{
  "label": "AI evaluation",
  "score_label": "Ideal match - 92%",
  "reasons": [
    "Java/Spring experience matches the need",
    "Recent banking sector experience"
  ]
}
```

`reasons` should be short and grounded in backend data.

## Experience Object

```json
{
  "title": "Senior Java Software Engineer",
  "company": "EY",
  "period": "May 2023 - present"
}
```

## Lightweight Frontend Controls

For `candidate_cards`, the frontend may display:

- sort by `match_score`
- show only candidates whose `availability` already indicates quick availability

These controls are visual only. Backend filtering remains authoritative.

## Clarification

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
      }
    ]
  }
}
```

## Candidate Detail

`candidate_detail` uses the same candidate object as candidate cards:

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
      "skills": ["Java", "Spring Boot"],
      "experiences": [],
      "ai_evaluation": null
    }
  }
}
```

## Technical Summary

```json
{
  "conversation_id": "conv_123",
  "message": "Here is the technical analysis.",
  "ui": {
    "type": "technical_summary",
    "title": "Technical analysis - Sarah Martin",
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

## Security And Scope

- The frontend does not call MCP tools.
- The frontend does not call OpenAI directly.
- The frontend does not call BoondManager APIs directly.
- The frontend only opens `boond_url` when the backend provides it.
- The frontend must not implement candidate creation, candidate modification,
  generic BoondManager actions, confirmations, or generic table/list rendering.

## Error Handling

The frontend maps API failures to user-friendly messages:

- network error
- timeout
- malformed response
- generic backend error

Raw JSON must never be displayed to the user.
