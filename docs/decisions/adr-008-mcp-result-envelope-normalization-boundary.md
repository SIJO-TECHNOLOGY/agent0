# ADR-008 - MCP Result Envelope Normalization Boundary

## Context

ADR-007 closed the LLM-plan execution-semantics gap: bare `depends_on` is ordering only, fan-out is restricted to enrichment tools, and non-candidate tool output never pollutes the candidate list. Once those invariants landed, the streaming endpoint started doing exactly what it was supposed to do — it called `searchCandidates` for real, end to end.

That immediately revealed the next problem. The stream showed a successful `searchCandidates` invocation with `result_count: 1`, but the workflow normalized that result into a `SearchResult` with no resolvable id, then the candidate mapper dropped it, then the final message said "No candidates matched your search."

The observability work added during ADR-007 made the actual cause directly visible. `tool_call_completed` carries a sanitized `result_shape` summary, and for `searchCandidates` it reported:

```text
top_level_keys: ["candidates", "meta"]
nested_keys: { "candidates[0]": [..., "id", ...], "meta": ["currentPage", "totalRows"] }
record_count: 1
```

The MCP server returned a single envelope, not a list of records. The candidate ids lived one level down, under `candidates`.

## Problem

The Agent API's result normalizer (`coerce_records`) only knew the wrapper keys `results`, `items`, and `data`. When `searchCandidates` returned `{"candidates": [...], "meta": {...}}`, none of those keys matched, the whole envelope became one faux-record, and the rest of the workflow tried — and failed — to extract a candidate id from a payload whose only top-level keys were `candidates` and `meta`.

Three secondary issues hung off the primary defect:

- `meta` (the pagination block) is a dict at the top level, so without a guard it could be mistaken for a candidate record.
- Wrapper shapes like `{"candidates": ["alice", "bob"]}` (strings, not dicts) must never be misread as candidate records — the unwrap must be schema-aware enough to refuse non-record inputs.
- The mock MCP client used in tests returned handler output verbatim. Even after a fix in `RemoteMcpClient`, tests would not have caught a regression because the mock path never exercised the same normalizer.

## Decision

Envelope normalization is the responsibility of the **MCP client boundary**, applied uniformly to real and mock clients, with explicit safety guards.

### 1. Earliest safe layer

`coerce_records` lives at the MCP client boundary, not in the LangGraph node and not in the candidate mapper. Every downstream layer (`_record_to_result`, the candidate mapper, the fan-out executor) receives a clean `list[dict]`. The MCP client is the only place that needs to know what wrapper shape a given server uses.

Implementation: `apps/agent-api/app/mcp/result_normalizer.py`.

### 2. Supported wrapper keys, ordered by priority

```text
("results", "items", "data", "candidates")
```

The list is intentionally short and generic — not BoondManager-specific. Priority is first-match-wins; if both `results` and `candidates` are present, `results` is unwrapped. New wrapper shapes (`rows`, `hits`, `records`, etc.) are an additive change to this tuple, never a re-architecture.

Implementation: `apps/agent-api/app/mcp/result_normalizer.py` `_UNWRAP_KEYS`.

### 3. Unwrap only when the inner value is `list[dict]`

The single hard rule of the normalizer. A wrapper key whose value is a dict, or a list of strings, or any non-`list[dict]` shape is **not** unwrapped — the envelope becomes one record and the downstream mapper decides what to do with it. This guarantees that `{"candidates": ["alice", "bob"]}` is never misread as candidate records.

Implementation: same file, the `all(isinstance(i, dict) for i in inner)` predicate.

### 4. `meta` is never spawned as a candidate

The mapper's id-resolution path requires a real candidate id; pagination metadata has none and is dropped cleanly. We do not need a special case for `meta`; the candidate-id guard is sufficient.

### 5. Real and mock MCP clients share the same normalizer

`RemoteMcpClient._normalize_result` and `MockMcpClient.call_tool` both route their output through the same `coerce_records`. This is load-bearing: it lets tests use realistic production envelopes (`{"candidates": [...], "meta": {...}}`) and exercise the same code path the live MCP client takes.

Implementation: `apps/agent-api/app/mcp/remote_client.py` and `apps/agent-api/app/mcp/mock_client.py`.

### 6. Stream observability stays sanitized

`tool_call_completed.result_shape` exposes structural metadata only — record counts, top-level key names, the keys of a nested sample. No record values. Sanitized previews of actual records remain off by default and are gated by the `X-Agent-Debug: true` request header. Even in debug mode, strings are length-capped, lists are item-capped, recursion is depth-capped, and known-sensitive key names (`token`, `password`, `cv_text`, etc.) are redacted regardless of value.

Implementation: `apps/agent-api/app/graph/nodes.py` `_emit_tool_completed`, and `apps/agent-api/app/services/result_inspector.py`.

## Consequences

Positive outcomes:

- `searchCandidates` payloads with the production envelope shape unwrap correctly: each item in `candidates[]` becomes a SearchResult, the candidate mapper produces cards, and the fan-out executor uses the real ids for `getCandidateDetail` and `getCandidateTechnicalDocument`.
- The stream now tells operators *what shape the MCP server actually returned* without needing log access, while never exposing raw payloads outside debug mode.
- Future MCP servers that use a different wrapper key are a single-line addition.
- Mock-mode tests can exercise production-like envelopes, so regressions in wire-shape handling are caught locally.

Tradeoffs:

- The mock client now applies a small amount of normalization. Test handlers must continue to return either a `list[dict]` or a wrapper envelope — non-record shapes raise `McpToolError` at call time, by design.
- The unwrap key list is shared across all MCP tools. A hypothetical future tool whose top-level `candidates` field is *not* a candidate list (a project that lists recommended people, for example) would be incorrectly unwrapped. The `list[dict]` guard reduces but does not eliminate this risk; the priority list is short by design so this stays a noticeable and reviewable change.

Validation evidence:

- `apps/agent-api/tests/test_mcp_result_normalizer.py` — confirms `{"candidates": [...], "meta": {...}}` unwraps; confirms `list[dict]` guard refuses to unwrap string lists; confirms legacy `results` / `items` / `data` shapes still work; confirms priority order.
- Wrapper-envelope regression tests in `apps/agent-api/tests/test_api_search_stream.py` — confirm end-to-end stream behaviour: real candidate ids appear in `results_normalized.candidate_ids`, fan-out hits the right ids, and the "could not be normalized" / "No candidates matched" misleading messages are gone.

Remaining boundary:

- This decision normalizes the *envelope*. It does not standardize the per-record shape. Future records that carry candidate ids at a path beyond the mapper's current set of fallbacks (`id`, `attributes.id`, `candidateId`, `candidate_id`, `_id`, `uuid`, `guid`, `key`) will surface via the drop-diagnostic field on the stream and require an additive change to the mapper, not the normalizer.

## Decision Flow

- System context: [Sijo AI Agent Architecture](../architecture/sijo-ai-agent-architecture.md).
- Builds on: [ADR-007 - LLM Tool Plan Execution Semantics](./adr-007-llm-tool-plan-execution-semantics.md). The envelope problem only became visible once the executor reliably reached `searchCandidates`.
- Preserves: [ADR-006 - User-Facing Search Streaming Strategy](./adr-006-user-facing-search-streaming-strategy.md). All observability additions (the shape summary, the debug preview, drop diagnostics) respect the sanitization rules ADR-006 set out.
- Preserves: [ADR-002 - MCP Client Wiring Review](./adr-002-mcp-client-wiring-review.md). MCP access remains behind a single client abstraction; the normalizer lives at that boundary.
- Linked forward: [ADR-009 - Agent API Milestone 1 Boundary And Evidence Verification](./adr-009-agent-api-milestone-1-boundary.md). With wrapper handling correct, the end-to-end milestone became reachable.

## Conclusion

A `{"candidates": [...], "meta": {...}}` envelope is one of the four wrapper shapes the Agent API now recognises at the MCP client boundary. The guard rule — unwrap only when the inner value is `list[dict]` — keeps the rule safe. The real and mock MCP clients run the same normalizer so tests cannot drift from production. And the stream's structural shape summary makes the *next* unknown payload diagnosable from outside, without dumping raw MCP output to the frontend.
