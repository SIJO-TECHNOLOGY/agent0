# SIJO Assistant Frontend

Vanilla HTML/CSS/JavaScript frontend for the SIJO Assistant candidate-search POC.

## Scope

This frontend is limited to advanced candidate search workflows:

- Microsoft SSO authentication
- candidate search chat
- candidate cards
- candidate detail
- technical candidate summary
- clarification forms
- conversation history

It is not a generic BoondManager assistant.

## Run Locally

From this folder:

```bash
python -m http.server 5500
```

Then open:

```txt
http://localhost:5500
```

## Development Mode

`DEV_MODE` is configured in `config.js`.

When `DEV_MODE = true`:

- Microsoft auth is bypassed.
- A mock user is used.
- `/api/chat` returns mock candidate responses.
- No backend is required to test the UI.

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
