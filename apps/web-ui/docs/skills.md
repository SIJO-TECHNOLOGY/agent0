# Skills

## Purpose

This document describes the frontend capabilities required for the SIJO Assistant candidate-search POC.

## User-Facing Skills

### Candidate Search

The user can ask for candidates using natural language, for example:

- “Find Java candidates in Paris.”
- “Show me backend Java profiles.”
- “Find available fullstack candidates.”

The backend interprets the request and returns a response with `ui.type = "candidate_cards"` when structured candidate results are available.

The first screen and input help the user formulate a complete candidate need:

- role
- location
- experience level
- skills
- sector
- availability
- contract
- daily rate or salary

### Candidate Cards

Candidate cards display:

- Full name
- Title
- Experience
- Location
- Contract preference
- Availability
- Skills
- Match score
- Summary
- Recent experiences when provided
- Highlight keywords when provided
- AI evaluation when provided
- Strengths and watch points when provided
- Optional BoondManager URL button

The frontend displays cards only when the backend response explicitly asks for `candidate_cards`.

Candidate result groups may also display:

- result title
- result subtitle
- applied filter badges
- lightweight local sorting by match score
- lightweight local "available profiles" display toggle

These controls only affect already received candidates. They do not build
BoondManager queries.

### Candidate Detail

The frontend can display a detailed candidate profile when the backend returns `ui.type = "candidate_detail"`.

Candidate detail may include:

- Full name
- Title
- Location
- Availability
- Experience
- Contract preferences
- Salary expectation
- TJM
- Mobility
- Skills
- Experiences
- AI evaluation
- Technical summary
- Summary

### Technical Summary

The frontend can display a technical candidate analysis when the backend returns `ui.type = "technical_summary"`.

Technical summary may include:

- Title
- Summary
- Strengths
- Weaknesses
- Languages
- Tools and levels

### Clarification

When the request is ambiguous, the backend may return `ui.type = "clarification"`.

The frontend displays a compact form inside the chat and submits structured values back to the backend.

### Authentication

In production mode, the user must authenticate with Microsoft SSO before the chat is displayed.

In development mode, authentication is mocked.

## Developer Skills

Contributors should be comfortable with:

- Vanilla JavaScript modules
- DOM rendering without a framework
- REST API integration
- MSAL Browser authentication flow
- Defensive API response validation
- Accessible and responsive HTML/CSS

## Explicit Non-Skills

The frontend must not implement:

- MCP tool calls
- OpenAI API calls
- BoondManager API calls
- Generic CRUD workflows
- Generic table/list/action rendering
- Backend business logic
