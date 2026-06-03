# Milestones

This folder records system delivery milestones — the achieved state of the platform at clearly bounded moments in its evolution.

A milestone document is not an Architecture Decision Record. Where an ADR explains *why* a decision was made, a milestone explains *what shipped*, *what evidence proves it shipped*, and *what is honestly still outside the milestone's scope*. The two surfaces are complementary: ADRs in [`../decisions/`](../decisions/) explain the choices; milestones here certify the deliveries those choices added up to.

Each milestone uses the same lightweight template:

- **Status** — `Achieved` only when there is reproducible evidence; otherwise `In progress` or `Planned`.
- **Date** — when the milestone was certified.
- **Objective** — one short paragraph describing the delivery boundary.
- **Scope** — what this milestone includes.
- **Acceptance Criteria** — checklist of required outcomes.
- **Verification Evidence** — commands, anchor regression tests, and structural observations a future reader can re-run.
- **Known Limitations** — honest remaining gaps that do not block this milestone.
- **Related ADRs** — the decisions behind the milestone.
- **Next Milestone Candidates** — short list of logical next work.

## Milestones

- [Milestone 001 - Agent API MCP Fuzzy Search](./milestone-001-agent-api-mcp-fuzzy-search.md) — fuzzy natural-language queries reach the Agent API, an LLM plans MCP tool calls over a discovered catalogue, LangGraph executes them, and the frontend receives normalized candidate cards.
- [Milestone 002 - Bounded ReAct Control Loop](./milestone-002-bounded-react-control-loop.md) — planned certification for LLM observe-then-replan under LangGraph guardrails, including one-time guidance consumption, loop caps, fail-safe reflection, and safe streaming evidence.
