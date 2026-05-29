# Milestone 001 - Agent API MCP Fuzzy Search

## Status

Achieved

## Date

2026-05-29

## Objective

The Agent API accepts a fuzzy, natural-language query and returns a frontend-ready candidate-cards response, with all data access flowing through the MCP boundary. An LLM planner interprets the query against the MCP server's discovered tool catalogue, LangGraph validates and executes the resulting bounded plan, and a separate streaming endpoint exposes the workflow as sanitized progress events. The synchronous and streaming surfaces share the same orchestration core.

## Scope

This milestone covers orchestration and frontend-contract delivery for the first vertical search path:

- Fuzzy query intake on `POST /api/search` and `POST /api/search/stream`.
- LLM-led tool planning over discovered MCP tool metadata, with strict plan validation and bounded fan-out.
- MCP execution through a single `McpClient` abstraction (real Streamable HTTP transport or in-memory mock).
- Normalization of MCP records into the public `candidate_cards` UI shape, with diagnostics on the streaming endpoint when records cannot be normalized.
- Sanitized SSE-style progress events for the frontend, separate from the internal MCP transport.
- Liveness, readiness, and graceful MCP degradation as defined in earlier ADRs.

Not in scope (see Known Limitations below): deep verification of natural-language criteria that require parsing candidate technical documents.

## Acceptance Criteria

- [x] Fuzzy natural-language query is accepted by both `POST /api/search` and `POST /api/search/stream`.
- [x] MCP tools are discovered from a real MCP server at startup; the catalogue is visible on the streaming endpoint via `tools_discovered`.
- [x] The LLM planner produces a bounded, schema-validated plan over the discovered tools.
- [x] MCP tools execute only through the `McpClient` abstraction. No direct provider calls anywhere in the Agent API.
- [x] `POST /api/search/stream` emits the ADR-006 progress event sequence and terminates with `final_response` or `search_failed`.
- [x] `final_response.ui.type == "candidate_cards"`.
- [x] When `searchCandidates` returns one or more candidate records, `final_response.ui.candidates` contains real MCP candidate ids — never the `"unknown"` placeholder.
- [x] `GET /api/health` and `GET /api/ready` behave per ADR-003 / ADR-004 under real-mode startup, including when the MCP server is unreachable at boot.

## Verification Evidence

- 250 tests passing across the agent-api package at the time of certification (`uv run pytest -q`).
- Anchor regression tests a future reader can re-run to re-verify the milestone:
  - `apps/agent-api/tests/test_api_search_stream.py::test_stream_llm_path_emits_full_event_sequence` — full streaming happy path: planner mode, tool discovery, plan creation, validation, tool calls, normalization, and a `final_response` with `ui.type == "candidate_cards"`.
  - `apps/agent-api/tests/test_api_search_stream.py::test_wrapper_envelope_unwraps_into_search_results` — end-to-end against the production `{"candidates": [...], "meta": {...}}` envelope; confirms real candidate ids surface through to the public response.
  - `apps/agent-api/tests/test_mcp_result_normalizer.py::test_unwraps_candidates_envelope_into_list_of_records` — unit guarantee that the wrapper shape unwraps at the MCP client boundary.
- Reproducible manual check against a real MCP server (synthetic placeholders shown, structural assertions only):

  ```bash
  curl -N -X POST http://localhost:8000/api/search/stream \
    -H "Content-Type: application/json" \
    -d '{"query":"<fuzzy natural-language query>","filters":{}}'
  ```

  Expected stream shape (event names and structural fields only — values omitted):

  ```text
  event: search_started
  data: { "conversation_id": "<id>", "query": "<...>", "planner_mode": "llm" }

  event: tools_discovered
  data: { "tools": [ { "name": "<...>", "input_schema_keys": [ ... ] }, ... ] }

  event: plan_created
  data: { "plan": [ ... ], "assumptions": [], "warnings": [] }

  event: plan_validated
  data: { "accepted_steps": [ ... ], "rejected_steps": [ ... ] }

  event: tool_call_started
  data: { "tool": "<...>", "inputs": { ... } }

  event: tool_call_completed
  data: {
    "tool": "<...>",
    "status": "success",
    "result_count": <int>,
    "result_shape": { "record_count": <int>, "top_level_keys": [ ... ], "nested_keys": { ... } }
  }

  event: results_normalized
  data: {
    "raw_result_count": <int>,
    "candidate_count": <int>,
    "candidate_card_count": <int>,
    "candidate_ids": [ "<id>", ... ],
    "dropped_count": <int>,
    "drop_reasons": [ ... ]
  }

  event: candidate_cards_partial
  data: { "candidates": [ { "id": "<id>", ... }, ... ] }

  event: final_response
  data: {
    "conversation_id": "<id>",
    "message": "<...>",
    "ui": { "type": "candidate_cards", "candidates": [ ... ] }
  }
  ```

  Milestone-passing signal: the final event is `final_response`, `ui.type == "candidate_cards"`, and `ui.candidates` contains at least one entry with a real `id` whenever `searchCandidates` returned one or more records.

## Known Limitations

- `getCandidateTechnicalDocument` currently fails from the MCP / BoondManager side. The Agent API can call the tool and surface its failure on the stream, but it cannot use the data the tool was meant to return.
- As a direct consequence, deep natural-language criteria — for example "10+ years Java" or "last experience in CIB" — cannot be verified end to end yet. The `candidate_cards` returned are `searchCandidates` matches, not criterion-verified matches.
- The user-facing `message` field is honest about which terminal state the workflow reached (search did not complete / no candidates / records returned but unmappable / N candidates found), but it does not claim to have verified every clause of the user's query.

This milestone certifies orchestration and the frontend contract. It does **not** certify deep evidence verification; that is the boundary of the next milestone.

## Related ADRs

- [ADR-005 - Agent Planner Drift From LLM-Led Architecture](../decisions/adr-005-agent-planner-drift-from-llm-architecture.md)
- [ADR-006 - User-Facing Search Streaming Strategy](../decisions/adr-006-user-facing-search-streaming-strategy.md)
- [ADR-007 - LLM Tool Plan Execution Semantics](../decisions/adr-007-llm-tool-plan-execution-semantics.md)
- [ADR-008 - MCP Result Envelope Normalization Boundary](../decisions/adr-008-mcp-result-envelope-normalization-boundary.md)
- [ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification](../decisions/adr-009-agent-api-milestone-1-boundary.md)

## Next Milestone Candidates

- MCP technical-document reliability — `getCandidateTechnicalDocument` returns usable evidence data from BoondManager, including skills, experience timeline, and recent project context.
- Evidence-based ranking and messaging — once the technical-document path is reliable, surface verified-vs-keyword distinctions in both the candidate cards and the final user message.
- Optional WebSocket surface for bidirectional flows (user cancellation, mid-stream clarification, approval-before-tool-call), per the ADR-006 "Out of Scope" list.
