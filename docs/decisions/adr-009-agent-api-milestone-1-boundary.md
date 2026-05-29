# ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification

## Context

By the close of the ADR-008 work, every piece of the Agent API's first product loop was in place and behaving honestly under stream observation:

- The synchronous `POST /api/search` endpoint returns the frontend candidate-cards contract.
- The streaming `POST /api/search/stream` endpoint emits the full sequence of progress events agreed in ADR-006.
- An LLM planner discovers MCP tools from a real MCP server and emits a bounded, validated plan over them.
- LangGraph executes that plan through the MCP client, with ordering / fan-out / candidate-vs-context invariants from ADR-007 enforced.
- `searchCandidates` envelopes from the live MCP server unwrap cleanly per ADR-008; candidate ids are real BoondManager ids, never the `"unknown"` placeholder.
- Health and readiness behaviour from ADR-003 / ADR-004 is intact under real-mode startup.

What is *not* in place is deep evidence verification. Queries like "10+ years Java" or "last experience in CIB" require fetching and parsing candidate technical documents. That work currently fails from the MCP / BoondManager side: `getCandidateTechnicalDocument` does not yet return usable evidence data. The Agent API can call the tool, surface its failure on the stream, and continue — but it cannot verify a natural-language criterion that the upstream tool will not supply data for.

## Problem

Without an explicit boundary between "Agent API orchestration is done" and "criterion verification is done", the next iteration risks:

- More Agent API refactoring aimed at extracting evidence that the MCP side is not yet providing.
- Optimistic phrasing in the user-facing message ("found N candidates matching your criteria") when the deep criteria were never verifiable.
- Operational confusion about which side of the system owns the remaining precision gap.

The decision recorded here protects against all three. It declares Milestone 1 done for orchestration and frontend-contract delivery, and explicitly defers criterion-precision work to a later milestone scoped against MCP-side improvements.

## Decision

Treat **Agent API Milestone 1 as complete** for orchestration and frontend-contract delivery. Defer criterion-evidence work until the MCP server can reliably supply the underlying data.

Falsifiable acceptance line (verbatim, for unambiguous re-verification):

> Milestone 1 is complete iff `POST /api/search/stream` against a real MCP server emits `final_response.ui.type == "candidate_cards"` and includes at least one real candidate id when `searchCandidates` returns one or more candidate records.

This sentence is the only thing that defines Milestone 1 success. Anything beyond it — evidence verification, ranking precision, multi-turn refinement — is explicitly out of scope until a future milestone re-opens that surface, after the MCP tooling catches up.

In-scope responsibilities the Agent API retains under this decision:

- Maintain the public contract from ADR-006 (sanitized streaming events; no raw MCP / BoondManager payloads; no chain-of-thought).
- Maintain the LLM-plan invariants from ADR-007 (ordering vs. fan-out; candidate-producing allowlist; honest terminal messages).
- Maintain the envelope-normalization boundary from ADR-008.
- Continue to surface MCP-side failures truthfully via `tool_call_completed` and the existing message variants, without papering over them.

Out-of-scope under this decision (explicitly deferred):

- Evidence-based ranking that depends on `getCandidateTechnicalDocument` content.
- User-facing messaging that claims natural-language criteria were verified when only `searchCandidates` keywords were matched.
- Frontend implementation, including any UI affordance for "verified" vs. "candidate match" distinctions.
- Direct BoondManager access from any Agent API code path. The MCP boundary stays.

## Consequences

Positive outcomes:

- A single sentence defines done. Any future contributor can run one curl command against a real MCP server and judge the milestone.
- The team is shielded from the temptation to compensate for upstream data gaps by adding complexity to the Agent API.
- The next milestone has a clean starting point: MCP technical-document reliability, followed by evidence-based ranking and messaging on top of it.

Tradeoffs:

- The current product surface is honest but limited. A user who reads "I found 2 candidates matching your search" understands those are `searchCandidates` matches, not verified-on-all-criteria matches. We accept this until the evidence path is available.
- This decision binds the next iteration's scope. Re-opening Agent API refactoring before the MCP side has caught up requires either a new ADR or an explicit override of this one.

Validation evidence:

- 250 tests passing across the agent-api package at the time this ADR was written.
- Anchor regressions: `apps/agent-api/tests/test_api_search_stream.py::test_stream_llm_path_emits_full_event_sequence` covers the happy-path stream end to end; `apps/agent-api/tests/test_mcp_result_normalizer.py::test_unwraps_candidates_envelope_into_list_of_records` and `apps/agent-api/tests/test_api_search_stream.py::test_wrapper_envelope_unwraps_into_search_results` cover the production envelope shape that closed the loop.
- The same acceptance line above can be re-run by hand against a live MCP server; the milestone document records the exact curl shape and expected event sequence.

Remaining boundary:

- Deep criterion verification (years of experience, "last experience" sector matching, skill verification) is deferred to a future milestone gated by MCP-side technical-document availability.

## Decision Flow

- System context: [Sijo AI Agent Architecture](../architecture/sijo-ai-agent-architecture.md). The Agent API owns orchestration and the frontend boundary; the MCP server owns provider-specific data access.
- Builds on: [ADR-005 - Agent Planner Drift From LLM-Led Architecture](./adr-005-agent-planner-drift-from-llm-architecture.md). LLM planning is the primary real-mode path the milestone certifies.
- Builds on: [ADR-006 - User-Facing Search Streaming Strategy](./adr-006-user-facing-search-streaming-strategy.md). The streaming contract is the milestone's external surface.
- Builds on: [ADR-007 - LLM Tool Plan Execution Semantics](./adr-007-llm-tool-plan-execution-semantics.md). The invariants that make the stream tell the truth.
- Builds on: [ADR-008 - MCP Result Envelope Normalization Boundary](./adr-008-mcp-result-envelope-normalization-boundary.md). The wire-shape handling that made the happy path actually reach the user.
- Linked forward: [Milestone 001 - Agent API MCP Fuzzy Search](../milestones/milestone-001-agent-api-mcp-fuzzy-search.md). The recorded delivery state and verification evidence.

## Conclusion

Agent API Milestone 1 is the orchestration-and-frontend-contract milestone. It is complete when the falsifiable acceptance line above holds against a real MCP server, and the next round of work belongs to the MCP / data side, not to further Agent API refactoring.
