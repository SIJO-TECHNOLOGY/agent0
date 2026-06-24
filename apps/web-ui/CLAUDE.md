# SIJO Assistant Frontend

## Project Context

SIJO Assistant is an internal proof of concept focused on advanced candidate search. The frontend is a lightweight vanilla HTML/CSS/JavaScript application connected to a future FastAPI backend.

The application is not a generic BoondManager assistant. It must stay focused on candidate search workflows: candidate discovery, clarification questions, candidate detail display, and technical candidate summaries.

## Scope

Allowed frontend capabilities:

- Microsoft SSO authentication with MSAL.js.
- Chat interface for candidate search.
- Conversation history loaded from the backend.
- Candidate cards.
- Enriched candidate result summaries.
- AI match evaluation display.
- Resolved candidate metadata display.
- Diplomas, domains, tools, and languages display.
- Recent experience display.
- Lightweight display-only sorting/filtering of already received candidates.
- Candidate detail rendering.
- Candidate technical summary rendering.
- Clarification forms.
- Development mode with mocked candidate responses.

Out of scope:

- Direct OpenAI calls from the frontend.
- Direct MCP calls from the frontend.
- Direct BoondManager API calls from the frontend.
- Generic BoondManager actions.
- Write actions, confirmations, action IDs, generic tables, generic lists, or workflow automation UI.

## Stack

- HTML
- CSS
- Vanilla JavaScript modules
- MSAL Browser via CDN
- REST API calls to a FastAPI backend
- Node.js for local development scripts
- Vite for development server and production build
- `i18n.js` — lightweight custom i18n engine (FR/EN)

No React, Vue, Angular, or frontend framework should be introduced.

## Internationalisation

UI strings live in `locales/fr.js` (default) and `locales/en.js`.  
Use `t("key")` / `tCount("key", n)` — never hardcode strings in JS or HTML.  
Backend text (candidate data, error messages from the server) is **never** translated.

## Scroll Behaviour

The page auto-scrolls only when the **user** sends a message.  
Assistant responses, candidate cards, and loading indicators do **not** trigger auto-scroll — the user stays at their reading position.

## Key Constraints

- Keep the current SIJO V1 design and layout.
- Keep the existing candidate cards and conversation history behavior.
- Keep the frontend modular and easy to evolve.
- The backend owns conversation state; the frontend must not send full chat history.
- Chat requests must only send:

```json
{
  "message": "...",
  "conversation_id": "..."
}
```

- Clarification submissions may send a structured `interaction` object.
- All backend calls must include `Authorization: Bearer <token>` when `DEV_MODE` is false.
- No secrets, client secrets, API keys, MCP credentials, OpenAI keys, or BoondManager tokens can be stored in the frontend.

## Development Mode

`DEV_MODE` is configured in `config.js`.

When enabled:

- Microsoft authentication is bypassed.
- Authentication state is mocked.
- API responses are mocked in `api.js`.
- Candidate cards can be tested without a backend.
- Debug logs for normalized responses may appear in the console.
- The header user-name slot should remain blank until real identity display is
  implemented.

When disabled:

- Microsoft SSO is required before accessing the chat.
- Backend API calls must use the Microsoft access token.

## Local Development And Build

Use Node.js commands from the `frontend/` directory:

```bash
npm install
npm run dev
npm run build
npm run preview
```

`npm run dev` serves the frontend on `http://localhost:5500`.

`npm run build` generates static deployable files in `dist/`.

`dist/` and `node_modules/` are generated artifacts and should not be edited manually.

## Rendering Model

The frontend chooses the rendering based only on `ui.type` returned by the backend.

Supported UI types:

- `text`
- `candidate_cards`
- `clarification`
- `candidate_detail`
- `technical_summary`
- `error`
- `loading`

Do not add generic rendering primitives unless the candidate-search POC explicitly needs them.

For `candidate_cards`, the frontend may render optional fields:

- `ui.title`
- `ui.subtitle`
- `ui.filters_summary`
- `candidate.contract_preferences`
- `candidate.salary_expectation`
- `candidate.tjm`
- `candidate.mobility`
- `candidate.state_label`
- `candidate.source`
- `candidate.last_update`
- `candidate.ai_evaluation` or `candidate.match_explanation`
- `candidate.experiences`
- `candidate.highlights`
- `candidate.strengths` or `candidate.strong_points`
- `candidate.watch_points`, `candidate.weaknesses`, or `candidate.vigilance_points`
- `candidate.technical_summary`
- `candidate.diplomas`
- `candidate.expertise_areas`
- `candidate.activity_areas`
- `candidate.tools`
- `candidate.languages`

All these fields are optional. The frontend must remain robust when they are
missing.

Lightweight sorting/filtering is allowed only for already received candidate
cards. The frontend must not construct BoondManager queries or apply backend
business rules.

Candidate-search copy should stay natural. Do not surface backend warning codes,
criteria diagnostics, or long parenthesized technical explanations in normal
assistant messages.

## Backend Relationship

The backend may use tools such as candidate dictionaries, candidate search, candidate details, or technical documents. The frontend must not know or call those tools directly.

The frontend only consumes normalized REST responses from the backend.
