# Project Structure

## Current Frontend Structure

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
├── config.js
├── msalConfig.js
├── auth.js
├── api.js
├── app.js
└── CLAUDE.md
```

## File Responsibilities

### `index.html`

Static DOM structure. Keep it simple and framework-free.

Do not put application logic here.

### `style.css`

Single stylesheet for the POC.

It contains:

- Layout
- Login/loading states
- Sidebar
- Chat bubbles
- Candidate cards
- Candidate drawer
- Clarification form
- Candidate detail
- Technical summary
- Mobile responsive rules

### `config.js`

Central configuration:

- `API_URL`
- `DEV_MODE`
- `API_ENDPOINTS`
- `FEATURES`
- `UI_CONFIG`
- `CANDIDATE_CONFIG`

Prefer changing configuration here before editing rendering or API logic.

### `msalConfig.js`

Microsoft SSO configuration placeholders.

Expected values:

- `clientId`
- `tenantId`
- `redirectUri`

### `auth.js`

Authentication module.

Must not contain client secrets.

### `api.js`

Backend REST client.

Responsibilities:

- Build configured endpoints.
- Add bearer token when required.
- Timeout chat calls.
- Normalize chat responses.
- Validate supported `ui.type` values.
- Provide development mocks.

### `app.js`

UI controller.

Responsibilities:

- Wire DOM events.
- Manage startup flow.
- Render messages and candidate UI.
- Submit chat and clarification payloads.
- Open and close candidate drawer.

## Naming Guidance

Use explicit names:

- `renderCandidateCards`
- `renderCandidateDetail`
- `renderTechnicalSummary`
- `renderClarificationForm`
- `normalizeChatResponse`

Avoid generic names such as:

- `renderWidget`
- `renderComponent`
- `handleAction`

The frontend is intentionally narrow and candidate-focused.

## What Not To Add

Do not add:

- React/Vue/Angular
- Build toolchain unless explicitly required
- Frontend routing
- Global state library
- Direct OpenAI integration
- Direct MCP integration
- Direct BoondManager API integration
