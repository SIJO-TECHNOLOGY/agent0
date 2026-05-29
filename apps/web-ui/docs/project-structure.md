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
├── app.js
├── api.js
├── auth.js
├── config.js
├── msalConfig.js
├── package.json
├── package-lock.json
├── vite.config.js
├── README.md
├── .gitignore
└── CLAUDE.md
```

Generated folders:

```txt
frontend/
├── node_modules/
└── dist/
```

`node_modules/` is created by `npm install`.

`dist/` is created by `npm run build` and contains the deployable static build.

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
- Candidate result summary
- AI evaluation blocks
- Highlight tags
- Recent experience blocks
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
- Render enriched candidate card fields when provided.
- Apply display-only candidate sorting/filtering to already received results.
- Submit chat and clarification payloads.
- Open and close candidate drawer.

### `package.json`

Node.js project manifest.

Scripts:

- `npm run dev`: starts the Vite development server on `http://localhost:5500`
- `npm run build`: generates the production build in `dist/`
- `npm run preview`: previews the production build locally

### `vite.config.js`

Vite configuration for development and production builds.

The app remains vanilla HTML/CSS/JavaScript. Vite is used only as local tooling and build tooling, not as a frontend framework.

### `README.md`

Human-facing quickstart and project overview.

### `CLAUDE.md`

Coding-agent context, constraints, project scope, and restrictions.

## Naming Guidance

Use explicit names:

- `renderCandidateCards`
- `renderCandidateResultsToolbar`
- `renderAiEvaluation`
- `renderExperiences`
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
- Another build toolchain unless explicitly required
- Frontend routing
- Global state library
- Direct OpenAI integration
- Direct MCP integration
- Direct BoondManager API integration
