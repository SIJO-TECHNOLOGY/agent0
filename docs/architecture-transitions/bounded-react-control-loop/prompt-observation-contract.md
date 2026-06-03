# Prompt And Observation Contract

## Headline

Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop

## Purpose

The reflection prompt gives the LLM enough evidence to decide whether one more guided search pass is worth the cost. It must not expose private reasoning, raw provider payloads, or frontend-unstable internals.

## Allowed Observation Content

The LLM may receive:

- Original user query.
- A concise ranked-results summary.
- Candidate display names when available.
- Candidate titles or headline fields.
- Rounded scores.
- `is_full_match` status.
- Human-readable unmet criteria.
- Result count and whether no candidates were returned.
- User-safe warning categories when useful for the reflection decision.

## Disallowed Observation Content

The LLM must not receive:

- Raw MCP payloads.
- Raw BoondManager payloads.
- CV text or technical-document bodies beyond already sanitized summaries.
- API keys, tokens, credentials, cookies, or auth headers.
- Internal stack traces.
- LangGraph private state dumps.
- Chain-of-thought from previous LLM calls.
- Frontend-only hidden debug objects.

## Reflection Output

The LLM returns JSON only:

```json
{
  "needs_replan": true,
  "reason": "Top results miss the requested domain.",
  "guidance": "Prioritize CIB as the domain and broaden Java keywords only if no exact CIB match is found."
}
```

Rules:

- `needs_replan` must be `true` only when another pass could plausibly improve the answer.
- `reason` is a short user-safe explanation for observability.
- `guidance` is a concrete instruction for the next plan.
- Empty or vague guidance is treated as no replan.
- Malformed JSON is treated as `needs_replan=false`.

## Planning With Feedback

When `replan_feedback` is present, `plan_with_llm` passes it as previous-attempt guidance. The next plan should change the approach rather than repeat the same call.

Examples of acceptable guidance:

- Broaden one over-strict keyword.
- Drop a low-confidence constraint.
- Prioritize a named domain or role in `ranking_priority`.
- Search by a specific person name first.
- Enrich with the technical-document evidence tool when candidate summaries are inconclusive.

Examples of unacceptable guidance:

- "Try again."
- "Use all tools."
- "Ignore validation."
- "Call BoondManager directly."
- Any instruction that requires raw provider access outside MCP.

## Sanitization Rule

Reflection observations are an internal agent input, not a raw execution transcript. They should be compact, bounded, and safe enough to log at a structural level without exposing sensitive data.
