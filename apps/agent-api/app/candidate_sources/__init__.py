"""Provider-neutral candidate discovery sources.

This package hosts the abstraction that lets Agent0 discover candidates from
more than one provider:

- ``models``        — provider-neutral search intent + external evidence models.
- ``linkedin_web``  — external discovery from public LinkedIn pages via the
                      OpenAI Responses API web_search tool (Agent API only —
                      NEVER in mcp-boondmanager).

BoondManager discovery keeps living in the existing MCP path; this package is
purely additive.
"""
