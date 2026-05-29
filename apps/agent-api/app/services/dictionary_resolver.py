"""Resolve a minimum-years-of-experience filter to an MCP dictionary id.

The Agent API treats this resolver as conservative best-effort:
- Only matches when a dictionary entry's label carries a clear numeric
  threshold (``"10+ years"``, ``"> 10 ans"``, ``"10 years and more"``).
- Never invents an id. Returns ``None`` when no entry matches.
- Picks the most-specific matching threshold (highest ``N ≤ min_years``)
  so we don't down-rank a senior candidate by choosing too loose a bucket.

This file knows nothing about BoondManager URLs or transports — it just
massages dictionary entries the MCP server already returned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

# "10+", "10 +", "10+ years", "10+ ans"
_PLUS_THRESHOLD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,3})\s*\+",
    re.IGNORECASE,
)

# "> 10", ">=10", "≥ 10"
_GTE_THRESHOLD_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:>=?|≥)\s*(\d{1,3})\b",
    re.IGNORECASE,
)

# "10 years and more", "10 years or more", "10 ans et plus"
_AND_MORE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,3})\s*(?:years?|yrs?|ans?)\s*(?:and|or|et|ou)\s*(?:more|plus)\b",
    re.IGNORECASE,
)


_LABEL_FIELDS: Final[tuple[str, ...]] = (
    "label",
    "name",
    "title",
    "value",
    "displayName",
)
_ID_FIELDS: Final[tuple[str, ...]] = ("id", "value", "key", "code")


def _label_of(entry: dict[str, object]) -> str | None:
    for field in _LABEL_FIELDS:
        candidate = entry.get(field)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    # JSON:API style: most fields live under "attributes".
    attributes = entry.get("attributes")
    if isinstance(attributes, dict):
        for field in _LABEL_FIELDS:
            candidate = attributes.get(field)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _id_of(entry: dict[str, object]) -> object | None:
    for field in _ID_FIELDS:
        candidate = entry.get(field)
        if candidate not in (None, ""):
            return candidate
    attributes = entry.get("attributes")
    if isinstance(attributes, dict):
        for field in _ID_FIELDS:
            candidate = attributes.get(field)
            if candidate not in (None, ""):
                return candidate
    return None


def _extract_lower_threshold(label: str) -> int | None:
    """Return the lower numeric bound implied by an open-ended label."""
    for pattern in (_PLUS_THRESHOLD_RE, _GTE_THRESHOLD_RE, _AND_MORE_RE):
        match = pattern.search(label)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def resolve_experience_id(
    entries: Iterable[object], min_years: int
) -> object | None:
    """Pick the dictionary id whose label matches the user's min years.

    Returns ``None`` if no entry has an unambiguous open-ended label
    with a numeric threshold less than or equal to ``min_years``.
    """
    if min_years < 0:
        return None

    candidates: list[tuple[int, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = _label_of(entry)
        if label is None:
            continue
        threshold = _extract_lower_threshold(label)
        if threshold is None:
            continue
        if threshold > min_years:
            continue
        entry_id = _id_of(entry)
        if entry_id is None:
            continue
        candidates.append((threshold, entry_id))

    if not candidates:
        return None
    # Highest matching threshold wins — most specific bucket.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
