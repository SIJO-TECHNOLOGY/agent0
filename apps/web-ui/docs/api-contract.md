# API Contract

## Base URL

Configured in `config.js`:

```js
export const API_URL = "http://localhost:8000";
```

## Authentication

When `DEV_MODE` is false, all backend calls must include:

```http
Authorization: Bearer <microsoft_access_token>
```

The backend validates the Microsoft token.

## Health

```http
GET /api/health
```

Expected response:

```json
{
  "status": "ok"
}
```

## Chat

```http
POST /api/chat
```

The frontend must not send full conversation history.

Request:

```json
{
  "message": "Find Java candidates in Paris",
  "conversation_id": "conv_123"
}
```

The frontend applies a timeout to this endpoint.

## Chat Response Envelope

Preferred response:

```json
{
  "conversation_id": "conv_123",
  "message": "I found matching candidates.",
  "ui": {
    "type": "candidate_cards"
  }
}
```

Legacy response still supported:

```json
{
  "conversation_id": "conv_123",
  "answer": "I found matching candidates.",
  "candidates": []
}
```

## Supported `ui.type`

Only these values are supported:

- `text`
- `candidate_cards`
- `clarification`
- `candidate_detail`
- `technical_summary`
- `error`
- `loading`

Unsupported UI types are treated as malformed responses.

## Candidate Cards

Used for candidate search results.

Example:

```json
{
  "conversation_id": "conv_123",
  "message": "I found 5 candidates matching your search.",
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

Legacy candidate location also works:

```json
{
  "answer": "I found candidates.",
  "candidates": []
}
```

## Clarification

Used when the backend needs more information.

Response:

```json
{
  "conversation_id": "conv_123",
  "message": "Can you specify the location or experience level?",
  "ui": {
    "type": "clarification",
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

Submission:

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
      "type": "clarification",
      "questions": []
    }
  }
}
```

## Candidate Detail

Used for a detailed candidate profile.

```json
{
  "conversation_id": "conv_123",
  "message": "Here is the candidate detail.",
  "ui": {
    "type": "candidate_detail",
    "candidate": {
      "full_name": "Sarah Martin",
      "title": "Backend Java Engineer",
      "location": "Paris",
      "availability": "Available immediately",
      "experience_years": 7,
      "contract_preferences": ["CDI", "Freelance"],
      "salary_expectation": "55k€",
      "tjm": "600€",
      "skills": ["Java", "Spring", "Kafka"],
      "summary": "Confirmed backend profile."
    }
  }
}
```

## Technical Summary

Used for candidate technical document analysis.

```json
{
  "conversation_id": "conv_123",
  "message": "Here is the technical analysis.",
  "ui": {
    "type": "technical_summary",
    "title": "Technical analysis — Sarah Martin",
    "summary": "Strong Java/Spring profile with microservices experience.",
    "strengths": ["Advanced Java", "Microservices architecture", "Kafka"],
    "weaknesses": ["Limited frontend experience"],
    "languages": ["Fluent French", "Professional English"],
    "tools": [
      { "name": "Java", "level": 5 },
      { "name": "Spring Boot", "level": 4 }
    ]
  }
}
```

## Conversations

```http
GET /api/conversations
```

```http
GET /api/conversations/{conversation_id}
```

```http
POST /api/conversations
```

```http
DELETE /api/conversations/{conversation_id}
```

The backend owns persistence and conversation memory.

## Error Handling

The frontend maps API failures to user-friendly messages:

- Network error
- Timeout
- Malformed response
- Generic backend error

Raw JSON must not be displayed to the user.

