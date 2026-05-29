"""Shared MCP tool-result normalization.

Lives at the MCP boundary so both ``RemoteMcpClient`` (real Streamable
HTTP transport) and ``MockMcpClient`` (in-memory tests) hand the rest
of the agent the *same* shape: ``list[dict[str, object]]``.

Common MCP servers return results in one of two ways:

- a flat ``list`` of record objects, or
- a single ``dict`` envelope that wraps the list under a well-known
  key (``results``, ``items``, ``data``, or ``candidates``) and may
  carry pagination metadata under ``meta`` / ``page`` / etc.

The unwrap key list is intentionally short and generic — not
BoondManager-specific. We only unwrap when the inner value is a
``list[dict]`` (so ``{"candidates": ["alice", "bob"]}`` would NOT
trigger an unwrap of a string list mistakenly typed as candidates).
"""

from __future__ import annotations

from typing import Final

from app.mcp.client import McpToolError

# Wrapper keys we'll unwrap, in priority order. Only the first match
# wins. Each candidate must point to a ``list[dict]`` to qualify.
_UNWRAP_KEYS: Final[tuple[str, ...]] = (
    "results",
    "items",
    "data",
    "candidates",
)


def coerce_records(value: object, *, tool: str) -> list[dict[str, object]]:
    """Coerce a structured MCP payload into ``list[dict]``.

    Raises ``McpToolError`` when the payload is neither a list of
    dicts nor a dict envelope — the agent surface needs a record list
    to feed ``_record_to_result`` / candidate mapping.
    """
    if isinstance(value, dict):
        for unwrap_key in _UNWRAP_KEYS:
            inner = value.get(unwrap_key)
            if isinstance(inner, list) and all(isinstance(i, dict) for i in inner):
                return [dict(i) for i in inner]
        # No known wrapper key matched — treat the whole dict as one
        # record and let the downstream mapper try to extract an id.
        return [dict(value)]

    if isinstance(value, list):
        records: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                raise McpToolError(
                    f"tool {tool!r} returned a list item that is not an object",
                    tool=tool,
                )
            records.append(dict(item))
        return records

    raise McpToolError(
        f"tool {tool!r} returned unsupported content of type "
        f"{type(value).__name__}",
        tool=tool,
    )
