# ADR-016: Backend security & correctness hardening

## Status

Accepted (2026-09-07)

## Context

Four related weaknesses surfaced in a review of the backend, spanning the
MCP server, the Agent API, and CI. They are recorded together because they
were addressed as one hardening pass and share a theme: the running system
should be correct and safe *by default*, not only when every switch is set
by hand.

- **Technical-document retrieval.** The MCP tool `getCandidateTechnicalDocument`
  called `GET /candidates/{id}/technical-data` and, on failure, a **guessed**
  fallback `GET /candidates/{id}/technical-datas` (plural). The DTO, tool
  description, and docs asserted that the returned `data.id` *is the candidate
  id*, conflating two distinct BoondManager identifiers: the candidate/profile
  id (`ID_PROFIL`) and the technical-document id (`ID_DT`, `TAB_DT`). A
  candidate with no technical document produced an error rather than an empty
  result.

- **Authentication default.** `require_auth` already validates Entra ID bearer
  tokens server-side, but `ENABLE_AUTH` defaulted to `false` in every
  environment. Nothing prevented a production instance from booting
  unauthenticated if the flag was forgotten — and frontend MSAL alone is not a
  security boundary, since nginx proxies `/api/*` straight to FastAPI.

- **Multi-user session isolation.** Durable conversation storage is partitioned
  by the Entra `oid`, but several *process-local* runtime stores were keyed by
  `conversation_id` alone: `SESSION_STORE` (session memory), `_queries`/`_pools`
  (query text and paginated result pools), and the `_CANDIDATES` card cache.
  Two authenticated users reusing the same conversation id could read or
  overwrite each other's runtime state, and `POST /api/chat/session/reset` took
  only a `sessionId` — with no user binding, any authenticated caller could
  reset another user's in-memory session.

- **CI quality gates.** Deployments ran on push to `main` and built/deployed
  the container images with no test run in between; the Java image build uses
  `mvn package -DskipTests`. Nothing guaranteed the deployed commit had passing
  tests.

## Decision

### Technical data — trust the documented candidate tab, do not invent a lookup

BoondManager exposes a candidate's technical document (dossier technique / DT)
through the **documented candidate-scoped tab** `GET /candidates/{id}/technical-data`
(a sibling of `information` and `administrative`; confirmed against external
BoondManager API clients/MCP servers and the `TAB_DT`/`TAB_PROFIL` schema
docs). BoondManager resolves the candidate → DT link **server-side** for that
route, so no separate `technicalDataId` lookup is needed or available.

Accordingly:

- Keep the candidate tab as the single source; **remove** the guessed plural
  fallback `/candidates/{id}/technical-datas`.
- The candidate id (`ID_PROFIL`) and the technical-document id (`ID_DT`,
  surfaced as `data.id`/`tdId`) are treated as **distinct identifiers**. The
  candidate id is only ever the `{id}` path segment; it is never used as a
  technical-data id, and the tool never issues `/technical-datas/{candidateId}`.
  `TechnicalDocumentDto.candidateId` (taken from the request) is the
  authoritative candidate id; `id`/`tdId` identify the document.
- A candidate with no technical document returns
  `TechnicalDocumentDto.notAvailable(candidateId)` (empty content, `candidateId`
  set) rather than an error — mirroring the empty-CV handling. A non-404 backend
  error still propagates.

We deliberately did **not** implement a two-step `technicalDataId` →
`GET /technical-datas/{technicalDataId}` flow: no candidate response the
application fetches exposes such a relationship, and the tab route already does
the resolution. Inventing that endpoint would have broken a working, documented
integration.

### Authentication — secure by default outside local/dev/test

`validate_auth_settings` (run at startup) now fails fast in **two** cases, not
one: (a) `ENABLE_AUTH=true` without `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID` (as
before), and (b) `ENABLE_AUTH=false` when `APP_ENV` is not one of
`local`/`dev`/`development`/`test`/`testing`/`ci`. The container image sets
`APP_ENV=production`, so a forgotten flag now stops the process instead of
silently serving unauthenticated. Auth stays off by default only in explicitly
local/dev/test environments, keeping development and the test suite
unauthenticated.

### Session isolation — a structured `(user_oid, conversation_id)` key

All process-local per-user state is keyed by a frozen
`SessionKey(user_oid, conversation_id)` dataclass rather than the conversation
id alone (a structured key, not an ambiguous `f"{user}:{conv}"` string). This
covers `SESSION_STORE`, `_queries`/`_pools`, and the `_CANDIDATES` card cache
(keyed by `(user_oid, candidate_id)`). `user_oid` is the authenticated Entra
`oid`, threaded from the route handlers through the session/conversation-memory
functions and `SearchService.search[_with_events]` (default `"dev"` when auth is
disabled, matching the durable store's convention).

`POST /api/chat/session/reset` now requires the authenticated user and deletes
only `(user_oid, session_id)`, so a caller can never reset another user's
session. Genuinely shared, immutable reference data (e.g. the dictionary cache,
ADR-013) is intentionally left global.

### CI — deploy only a tested commit

A `validate.yml` workflow runs on every pull request: `pytest` (agent-api),
`mvn test` (mcp-boondmanager), and `npm ci && npm run build` (web-ui). Each
deploy workflow additionally gains a `test`/`build-check` job that
`build-and-deploy` `needs`, so the image is built and deployed only after the
suite passes **for that same commit**. The Java image keeps `-DskipTests`: tests
are validated by the gate, not inside the image build, so they are not run
twice.

## Consequences

- The technical-document flow no longer carries a candidateId == technicalDataId
  assumption anywhere (code, DTO, tool description, README, CLAUDE.md), and the
  unverified plural endpoint is gone. "No technical document" is a clean empty
  result. If BoondManager ever *does* expose a distinct `technicalDataId`
  relationship on a candidate payload, revisit — but until a captured response
  proves it, the tab route stands.
- Production cannot boot unauthenticated by omission. The trade-off: a
  deployment to a non-local `APP_ENV` must set `ENABLE_AUTH=true` plus the Entra
  ids or it will fail fast at startup (intended). The test suite pins
  `APP_ENV=test` so a developer's `.env` cannot trip this.
- Cross-user runtime state bleed and cross-user reset are closed. Cost: every
  runtime-store call now carries `user_oid`; forgetting it falls back to the
  `"dev"` bucket rather than leaking across users. Isolation is covered by
  `tests/test_session_isolation.py`.
- A red test suite blocks deployment. PRs get the same signal early. The minor
  duplication (PR head vs. merge commit) is deliberate: the merge commit is the
  artifact that actually ships.
- Config hygiene: `.env.example` now uses the variable names the apps actually
  consume (`BOONDMANAGER_BASE_URL`, `BOONDMANAGER_JWT_CLIENT`) instead of stale
  ones, and `.gitignore` excludes `*.db` and `.claude/worktrees/`.
