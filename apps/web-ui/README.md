# SIJO Assistant Frontend

Vanilla HTML/CSS/JavaScript frontend for the SIJO Assistant candidate-search POC.

## Scope

This frontend is limited to advanced candidate search workflows:

- Microsoft SSO authentication
- candidate search chat
- candidate cards
- enriched candidate result summaries
- AI match evaluation display
- recent experience display
- lightweight display-only sorting/filtering of received results
- candidate detail
- technical candidate summary
- clarification forms
- conversation history

It is not a generic BoondManager assistant.

## Run Locally With Node.js

From this folder:

```bash
npm install
npm run dev
```

Then open:

```txt
http://localhost:5500
```

## Build For Deployment

Generate the static production build:

```bash
npm run build
```

The deployable files are generated in:

```txt
dist/
```

Preview the production build locally:

```bash
npm run preview
```

## Development Mode

`DEV_MODE` is configured in `config.js`.

The committed default should stay:

```js
export const DEV_MODE = false;
```

This keeps Microsoft authentication enabled and sends real requests to the
backend.

When `DEV_MODE = true`:

- Microsoft auth is bypassed.
- A mock user is used.
- `/api/chat` returns mock candidate responses.
- Mock candidates include enriched optional fields for UI testing.
- No backend is required to test the UI.

For local UI-only testing, temporarily switch `config.js` to:

```js
export const DEV_MODE = true;
```

When `DEV_MODE = false`:

- Microsoft SSO is required.
- Backend requests include a bearer token.

## Main Files

```txt
frontend/
├── assets/
│   └── logo.png
├── docs/
│   ├── api-contract.md
│   ├── api-contract-detailed.md
│   ├── architecture.md
│   ├── design.md
│   ├── project-structure.md
│   └── skills.md
├── index.html
├── style.css
├── app.js
├── api.js
├── auth.js
├── config.js
├── msalConfig.js
├── README.md
└── CLAUDE.md
```

## Documentation

- `CLAUDE.md`: project context and constraints for coding agents.
- `docs/architecture.md`: architecture overview.
- `docs/api-contract.md`: concise API contract.
- `docs/api-contract-detailed.md`: detailed backend contract.
- `docs/project-structure.md`: file responsibilities.
- `docs/design.md`: UI principles.
- `docs/skills.md`: product capabilities.

## Restrictions

The frontend must never:

- call OpenAI directly
- call MCP tools directly
- call BoondManager APIs directly
- store backend secrets
- store Microsoft client secrets
- send full conversation history to the backend

The backend owns candidate search logic, conversation memory, and tool usage.

## Enriched Candidate UI

Candidate card responses may include optional sourcing fields such as:

- result title, subtitle, and filter summary badges
- contract preferences
- salary expectation
- TJM
- mobility
- AI evaluation or match explanation
- recent experiences
- highlight keywords
- strengths and watch points
- technical summary

The frontend displays these fields when present and hides them when absent. It
does not invent candidate data and does not build BoondManager queries.
