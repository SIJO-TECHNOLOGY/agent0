# Architecture

## Overview

SIJO Assistant Frontend is a static vanilla JavaScript application that talks only to a FastAPI backend.

```mermaid
flowchart LR
  User["Internal SIJO User"] --> Frontend["HTML/CSS/Vanilla JS Frontend"]
  Frontend --> Auth["Microsoft SSO via MSAL.js"]
  Frontend --> API["FastAPI Backend REST API"]
  API --> Agent["Candidate Search Agent"]
  Agent --> MCP["Candidate MCP / Boond-related Backend Tools"]
  Agent --> Data["Backend Database / Candidate Data"]
```

The frontend never calls MCP, OpenAI, or BoondManager APIs directly.

## Main Layers

### `index.html`

Defines the static shell:

- Login screen
- Loading screen
- Sidebar
- Header
- Chat area
- Input area
- Candidate drawer

### `style.css`

Defines the complete visual system:

- SIJO layout
- Login and loading screens
- Chat bubbles
- Candidate cards
- Clarification forms
- Candidate detail and technical summary cards
- Candidate drawer
- Responsive behavior

### `config.js`

Centralizes:

- API base URL
- Development mode
- API endpoints
- Feature flags
- UI messages
- Candidate display settings

### `msalConfig.js`

Contains Microsoft SSO public configuration placeholders.

No client secret is stored in the frontend.

### `auth.js`

Owns authentication:

- `handleRedirect()`
- `login()`
- `logout()`
- `getCurrentUser()`
- `getAccessToken()`
- `isAuthenticated()`

In `DEV_MODE`, MSAL is bypassed.

### `api.js`

Owns backend communication:

- Builds endpoints from configuration.
- Adds authorization headers.
- Applies timeout on `/api/chat`.
- Validates and normalizes chat responses.
- Keeps development mock responses.

### `app.js`

Owns UI orchestration:

- Startup flow
- Authentication state display
- Conversation loading
- Sending chat messages
- Rendering assistant responses by `ui.type`
- Candidate drawer behavior
- Clarification submission

## Startup Flow

```mermaid
flowchart TD
  A["DOMContentLoaded"] --> B["showLoading()"]
  B --> C["handleRedirect()"]
  C --> D{"Authenticated?"}
  D -- "No" --> E["showLogin()"]
  D -- "Yes" --> F["showChat()"]
  F --> G["loadConversationsSafely()"]
```

The UI must never leave both login and chat hidden.

## Chat Flow

```mermaid
flowchart TD
  A["User sends message"] --> B["Render user bubble"]
  B --> C["Render loading bubble"]
  C --> D["POST /api/chat"]
  D --> E["Normalize response"]
  E --> F{"ui.type"}
  F --> G["text"]
  F --> H["candidate_cards"]
  F --> I["clarification"]
  F --> J["candidate_detail"]
  F --> K["technical_summary"]
  F --> L["error"]
```

## State Ownership

The backend owns:

- Conversation memory
- Candidate search intent
- Filters
- Tool usage
- Candidate retrieval
- Candidate technical analysis

The frontend owns:

- Current UI state
- Current conversation ID
- Current open candidate drawer
- Rendering only

