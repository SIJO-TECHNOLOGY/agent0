"""Sanitized observability helpers for MCP tool outputs.

These helpers feed the streaming endpoint so the frontend (or a
debugging operator) can understand what the MCP server actually
returned without ever seeing raw payloads.

Two modes:

- **Shape summary** (always safe). Returns a small dict of structural
  metadata: record count, top-level keys, the keys of a nested
  sample. **No values.** Safe to emit in normal stream mode.
- **Sanitized preview** (debug only). Returns a small, truncated,
  redacted view of the first few records. Strings are length-capped,
  arrays are item-capped, recursion is depth-capped, and sensitive
  keys are redacted regardless of value. Only emitted when the
  caller explicitly opts in (e.g. ``X-Agent-Debug: true``).
"""

from __future__ import annotations

from typing import Final

_DEFAULT_TOP_KEY_CAP: Final[int] = 30
_DEFAULT_NESTED_KEY_CAP: Final[int] = 30
_DEFAULT_PREVIEW_MAX_RECORDS: Final[int] = 2
_DEFAULT_PREVIEW_MAX_STR: Final[int] = 200
_DEFAULT_PREVIEW_MAX_DEPTH: Final[int] = 3
_DEFAULT_PREVIEW_LIST_CAP: Final[int] = 10
_DEFAULT_PREVIEW_DICT_CAP: Final[int] = 50

# Case-insensitive substrings that, when present in a key name, cause
# the value to be redacted in sanitized previews.
_REDACT_SUBSTRINGS: Final[tuple[str, ...]] = (
    "password",
    "secret",
    "token",
    "apikey",
    "api_key",
    "authorization",
    "auth_header",
    "credential",
    "cv_text",
    "resume_text",
    "cv_body",
    "private_key",
)


def summarize_result_shape(records: list[object]) -> dict[str, object]:
    """Return a sanitized shape summary for a list of MCP records.

    Always safe to emit: contains only structural metadata (counts and
    key names), never any values from the underlying payload.
    """
    record_count = len(records)
    sample = next((r for r in records if isinstance(r, dict)), None)
    if sample is None:
        sample_type = type(records[0]).__name__ if records else None
        return {
            "record_count": record_count,
            "top_level_keys": [],
            "nested_keys": {},
            "sample_type": sample_type,
        }

    top_keys = sorted(str(k) for k in sample.keys())[:_DEFAULT_TOP_KEY_CAP]
    nested: dict[str, list[str]] = {}
    for key, value in sample.items():
        if isinstance(value, dict):
            nested[str(key)] = sorted(str(k) for k in value.keys())[
                :_DEFAULT_NESTED_KEY_CAP
            ]
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            nested[f"{key}[0]"] = sorted(str(k) for k in value[0].keys())[
                :_DEFAULT_NESTED_KEY_CAP
            ]
    return {
        "record_count": record_count,
        "top_level_keys": top_keys,
        "nested_keys": nested,
    }


def sanitized_preview(records: list[object]) -> list[object]:
    """Return a sanitized, truncated, redacted preview of up to a few records.

    Intended **only** for debug mode. Strings are length-capped, arrays
    are item-capped, recursion is depth-capped, and known-sensitive
    keys are redacted regardless of their value.
    """
    return [
        _sanitize_value(record, depth=0)
        for record in records[:_DEFAULT_PREVIEW_MAX_RECORDS]
    ]


def _should_redact(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(needle in lowered for needle in _REDACT_SUBSTRINGS)


def _sanitize_value(value: object, *, depth: int) -> object:
    if depth > _DEFAULT_PREVIEW_MAX_DEPTH:
        return "...(depth-truncated)"
    if isinstance(value, str):
        if len(value) <= _DEFAULT_PREVIEW_MAX_STR:
            return value
        return value[:_DEFAULT_PREVIEW_MAX_STR] + "...(truncated)"
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for index, (key, inner) in enumerate(value.items()):
            if index >= _DEFAULT_PREVIEW_DICT_CAP:
                out["...(dict-truncated)"] = True
                break
            if _should_redact(key):
                out[str(key)] = "...(redacted)"
            else:
                out[str(key)] = _sanitize_value(inner, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [
            _sanitize_value(item, depth=depth + 1)
            for item in value[:_DEFAULT_PREVIEW_LIST_CAP]
        ]
    return type(value).__name__
