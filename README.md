# Sijo AI Agent

Internal monorepo for the Sijo AI Agent project.

The project connects an LLM-powered agent to BoondManager through an MCP server, allowing users to perform deep searches on BoondManager data with natural language.

## Current Status

This repository contains the active Sijo AI Agent implementation and its architecture documentation.

The current Agent API direction is an **Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop**: the LLM can observe sanitized ranked results and decide whether one more guided search pass is warranted, while LangGraph enforces bounded execution.

## Repository Structure

```text
.
├── apps/
│   ├── web-ui/
│   ├── agent-api/
│   └── mcp-boondmanager/
├── packages/
│   ├── shared-contracts/
│   └── prompts/
├── docs/
│   ├── architecture/
│   ├── architecture-transitions/
│   ├── mcp-tools/
│   ├── workflows/
│   ├── decisions/
│   ├── milestones/
│   └── diagrams/
├── infra/
│   ├── docker/
│   ├── compose/
│   └── scripts/
├── .env.example
├── README.md
└── Makefile
```

## Folder Guide

- `apps/web-ui`: Simple HTML, CSS, and JavaScript frontend for user searches and result display.
- `apps/agent-api`: LangGraph-based agent backend connected to an LLM and MCP tools.
- `apps/mcp-boondmanager`: Spring Boot MCP server exposing deterministic BoondManager tools.
- `packages/shared-contracts`: Shared schemas, API contracts, and response formats.
- `packages/prompts`: Prompt templates and agent instructions.
- `docs/architecture`: Architecture documents and system design notes.
- `docs/architecture-transitions`: Major architecture migration tracks, including bounded ReAct control-loop migration.
- `docs/mcp-tools`: MCP tool specifications and contracts.
- `docs/workflows`: User and agent workflow documentation.
- `docs/decisions`: Architecture decision records and tradeoff notes.
- `docs/milestones`: Delivery milestones and verification evidence.
- `docs/diagrams`: Mermaid diagrams and exported diagram assets.
- `infra/docker`: Docker-related placeholders and future build assets.
- `infra/compose`: Docker Compose placeholders for local orchestration.
- `infra/scripts`: Infrastructure and developer workflow scripts.

## Project Documentation

Start with the architecture overview:

- [Sijo AI Agent Architecture](./docs/architecture/sijo-ai-agent-architecture.md)
- [Architectural Paradigm Shift: From Single-Shot Planning to Bounded ReAct Control Loop](./docs/architecture-transitions/bounded-react-control-loop/README.md)

## Principles

- Keep the MCP server deterministic and non-intelligent.
- Keep LLM reasoning inside the agent backend.
- Keep agent control loops bounded, validated, and observable.
- Keep the first implementation path small and complete.
- Prefer explicit contracts and Markdown documentation before code.
- Avoid framework boilerplate until the project boundaries are stable.
