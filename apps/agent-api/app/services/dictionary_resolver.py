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


def dictionary_section_entries(
    raw_records: Iterable[object], section: str
) -> list[dict[str, object]]:
    """Collect dictionary entries for a named section (e.g. ``"tool"``).

    The real ``getDictionary`` returns a single record shaped like
    ``{"setting": {"experience": [...], "tool": [...]}}``; older/mock
    shapes may expose ``{section: [...]}`` directly or already be a flat
    list of entries. This normalizes all three so callers always get a
    flat ``list[dict]`` for the requested section.
    """
    out: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        direct = record.get(section)
        if isinstance(direct, list):
            out.extend(e for e in direct if isinstance(e, dict))
        setting = record.get("setting")
        if isinstance(setting, dict):
            nested = setting.get(section)
            if isinstance(nested, list):
                out.extend(e for e in nested if isinstance(e, dict))
    return out


def resolve_tool_ids(
    entries: Iterable[object], wanted_labels: Iterable[str]
) -> list[object]:
    """Best-effort: map tool/skill names to their dictionary ids.

    Case-insensitive exact label match against the ``setting.tool``
    dictionary. Returns the matched ids (de-duplicated, in dictionary
    order). Never invents an id — labels with no match are omitted, so a
    non-tool entity (e.g. a company name) simply contributes nothing.
    """
    wanted = {
        label.strip().lower()
        for label in wanted_labels
        if isinstance(label, str) and label.strip()
    }
    if not wanted:
        return []
    matched: list[object] = []
    seen: set[object] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = _label_of(entry)
        if label is None or label.strip().lower() not in wanted:
            continue
        entry_id = _id_of(entry)
        if entry_id is not None and entry_id not in seen:
            seen.add(entry_id)
            matched.append(entry_id)
    return matched


def experience_years_for_id(
    entries: Iterable[object], exp_id: object
) -> int | None:
    """Reverse lookup: a candidate's experience level id → years threshold.

    Finds the dictionary entry whose id matches ``exp_id`` and parses the
    open-ended lower bound from its label (e.g. ``"10+ years"`` → ``10``).
    Returns ``None`` when the id is unknown or its label carries no
    open-ended numeric threshold (e.g. a closed range like ``"1-3 years"``).
    """
    if exp_id in (None, ""):
        return None
    target = str(exp_id)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = _id_of(entry)
        if entry_id is None or str(entry_id) != target:
            continue
        label = _label_of(entry)
        return _extract_lower_threshold(label) if label else None
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
