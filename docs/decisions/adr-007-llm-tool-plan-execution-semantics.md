# ADR-007 - LLM Tool Plan Execution Semantics

## Context

ADR-005 restored the LLM as the primary real-mode planner: the Agent API hands the model the user query plus the discovered MCP tool catalogue, and the model emits a bounded, validated plan that LangGraph executes through the MCP client.

ADR-006 then made that plan executable as a *user-facing* progress stream: `POST /api/search/stream` emits `search_started`, `tools_discovered`, `plan_created`, `plan_validated`, `tool_call_started`, `tool_call_completed`, `results_normalized`, `candidate_cards_partial`, and `final_response`.

Once both decisions shipped, the stream surfaced an execution-semantics bug the synchronous endpoint had been hiding. The model began emitting plans that mixed two kinds of dependencies in a single field (`depends_on`):

- "Run B *after* A so A's side effect is in place." Typical use: call `getDictionary` first, then call `searchCandidates` so the LLM can reason about which inputs to use.
- "Run B *once per result* produced by A." Typical use: call `getCandidateDetail` once per candidate id returned by `searchCandidates`.

The executor could not tell those two cases apart, so all `depends_on` steps were routed through the candidate-id fan-out path.

## Problem

The user-visible symptom was a stream that looked successful but ended with a misleading final message.

Concrete sequence observed on the stream:

- `tool_call_started` `getDictionary`.
- `tool_call_completed` `getDictionary`, `status: "success"`, `result_count: 1`.
- `tool_call_started` for `searchCandidates` **never fired**.
- `tool_call_started` for `getCandidateDetail` / `getCandidateTechnicalDocument` **never fired**.
- `final_response.message`: "No candidates matched your search."

The root cause was three distinct defects, layered:

1. **Ambiguous `depends_on` semantics.** The executor treated *any* `depends_on` as a fan-out request. When `searchCandidates` carried `depends_on="getDictionary"` (the model meant "run after"), the executor tried to extract candidate ids from the dictionary result, got none, and silently skipped the search.
2. **Non-candidate tool output polluting the candidate list.** Records returned by side-effect tools (e.g. `getDictionary`) were absorbed as `SearchResult` entries. That inflated counters, confused ranking, and let dictionary ids occasionally surface as candidate ids.
3. **Coarse final-message logic.** The message builder only knew "any tool was called → say no matches". It could not say "the candidate search did not actually run" or "the search ran and returned zero records" — both rendered as the same misleading sentence.

## Decision

The Agent API now enforces three concrete invariants in the LLM plan executor and the user-facing message builder. Each is testable, and each is referenced from this ADR by `path:line` so future readers can confirm the code still matches the decision.

### 1. Ordering vs. fan-out are distinct

A bare `depends_on` (no `result_selector`) is an **ordering-only** relationship. The executor already runs plan steps in plan order, so a bare `depends_on` is documentary — the LLM must still supply every required schema input.

Fan-out requires **both** `depends_on` *and* `result_selector="candidate_ids"`. Only this pair triggers the per-candidate loop bounded by `NodeContext.max_enrichments`.

Implementation: `apps/agent-api/app/graph/nodes.py` `execute_llm_plan`, around lines 1441–1475 (the `is_fanout` predicate plus the direct-call branch).

### 2. Fan-out is restricted to enrichment tools

The planner's strict validator rejects `result_selector="candidate_ids"` on any tool that is not in the enrichment allowlist:

> `_FANOUT_ELIGIBLE_TOOLS = {"getCandidateDetail", "getCandidateTechnicalDocument"}`

This prevents the model from accidentally requesting fan-out on `searchCandidates` (which would make no semantic sense) and gives the validator a single, named invariant to maintain.

Implementation: `apps/agent-api/app/services/llm_planner.py` `_FANOUT_ELIGIBLE_TOOLS` and the validator branch that uses it.

### 3. Non-candidate tools never produce `SearchResult` entries

Records returned by tools outside the candidate-producing allowlist are never absorbed into `state.results`:

> `_CANDIDATE_PRODUCING_TOOLS = {"searchCandidates", "search_consultants", "getCandidateDetail"}`

`getDictionary`, `getCandidateTechnicalDocument`, and any future side-effect / context tool execute, surface their outcome on the stream, and stop there. They do not become candidates, they do not feed ranking, and they cannot be confused with search hits.

Implementation: `apps/agent-api/app/graph/nodes.py` `_CANDIDATE_PRODUCING_TOOLS` constant and the `_absorb_direct_outcome` guard.

### 4. Final message distinguishes three terminal states

The user-facing `_base_message` builder now picks between three messages when zero candidate cards exist:

- **Search did not complete** — no candidate-producing search tool ran (the case the bug exposed). The builder consults `_ran_candidate_search` against a small allowlist of search tools.
- **Search ran, zero matches** — a candidate-producing tool ran and returned zero records.
- **Records returned, normalization failed** — records came back from a candidate-producing tool but the mapper could not produce displayable cards.

Implementation: `apps/agent-api/app/services/search_service.py` `_base_message` plus `_CANDIDATE_SEARCH_TOOL_NAMES` and `_ran_candidate_search`.

## Consequences

Positive outcomes:

- The stream and the final response now agree. If `searchCandidates` never ran, the message says so; the operator no longer has to read events to know the search was a no-op.
- The validator catches schema-level misuse of fan-out at planning time, before any MCP call.
- Non-candidate tools (dictionaries, technical documents called as direct steps, future side-effect tools) cannot contaminate ranking or counters.
- Adding a future enrichment tool is a one-line change to `_FANOUT_ELIGIBLE_TOOLS`; adding a future candidate-producing tool is a one-line change to `_CANDIDATE_PRODUCING_TOOLS`.

Tradeoffs:

- The planning prompt and validator now carry two named allowlists. Both must be kept in sync with reality when the MCP catalogue grows.
- The LLM has to learn the ordering-vs-fan-out distinction. Plan validation rejects misuse, but a bad LLM plan still costs one round trip.

Validation evidence:

- Dictionary-before-search regression in `apps/agent-api/tests/test_api_search_stream.py` — confirms the ordering-only case runs `searchCandidates` after `getDictionary` and surfaces real candidate ids.
- "Search did not complete" / "no candidates matched" message-variant tests in the same file — confirm the three terminal states are distinguishable from the public response.
- LLM planner validator unit tests in `apps/agent-api/tests/test_llm_planner.py` — confirm `result_selector="candidate_ids"` on non-enrichment tools is rejected.

Remaining boundary:

- The Agent API can detect misuse of plan structure, but it cannot ensure the LLM produces a *useful* plan for a given query. Precision of the produced plan still depends on prompt quality and the published tool catalogue, both of which evolve independently of this ADR.

## Decision Flow

- System context: [Sijo AI Agent Architecture](../architecture/sijo-ai-agent-architecture.md). The Agent API owns planning and orchestration; MCP tools are the only data path.
- Builds on: [ADR-005 - Agent Planner Drift From LLM-Led Architecture](./adr-005-agent-planner-drift-from-llm-architecture.md). The invariants here only make sense once the LLM is the primary planner.
- Builds on: [ADR-006 - User-Facing Search Streaming Strategy](./adr-006-user-facing-search-streaming-strategy.md). Streaming made the silent fan-out collapse visible — the synchronous endpoint had been masking it.
- Linked forward: [ADR-008 - MCP Result Envelope Normalization Boundary](./adr-008-mcp-result-envelope-normalization-boundary.md). The next defect surfaced once these invariants landed and the stream finally reached `searchCandidates`: the wire payload turned out to use a wrapper shape the normalizer did not recognise.

## Conclusion

`depends_on` is now two distinct relationships expressed by two distinct fields: pure ordering (`depends_on` alone) and bounded fan-out (`depends_on` + `result_selector="candidate_ids"`). Fan-out is restricted to enrichment tools; non-candidate tools never become candidates; and the public message tells the truth about which terminal state the workflow actually reached. With these invariants in place, the LLM-led plan execution model is honest about what it did and what it did not do.
