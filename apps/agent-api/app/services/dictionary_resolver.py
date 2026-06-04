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


def entry_id_of(entry: dict[str, object]) -> object | None:
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
        entry_id = entry_id_of(entry)
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
        entry_id = entry_id_of(entry)
        if entry_id is None or str(entry_id) != target:
            continue
        label = _label_of(entry)
        return _extract_lower_threshold(label) if label else None
    return None


def dictionary_mobility_option_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract all mobility option entries from the BoondManager dictionary.

    BoondManager nests options under ``setting.mobilityArea[].option[]``.
    Returns a flat list of ``{id, label}`` dicts for label resolution.
    """
    out: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        setting = record.get("setting")
        if not isinstance(setting, dict):
            continue
        mobility_areas = setting.get("mobilityArea")
        if not isinstance(mobility_areas, list):
            continue
        for area in mobility_areas:
            if not isinstance(area, dict):
                continue
            options = area.get("option")
            if isinstance(options, list):
                out.extend(e for e in options if isinstance(e, dict))
    return out


def dictionary_tool_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract tool/technology entries from the BoondManager dictionary.

    Returns a flat list of ``{id, label}`` dicts, e.g.
    ``{"id": "ccc", "label": "C++"}``.
    """
    return list(dictionary_section_entries(raw_records, "tool"))


def dictionary_language_spoken_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract spoken-language entries from a BoondManager dictionary."""
    return list(dictionary_section_entries(raw_records, "languageSpoken"))


def dictionary_language_level_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract language-level entries from a BoondManager dictionary."""
    return list(dictionary_section_entries(raw_records, "languageLevel"))


def dictionary_activity_area_option_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract activity-area option entries from a BoondManager dictionary.

    BoondManager may expose activity areas either as a flat
    ``setting.activityArea[]`` list or as grouped entries with nested
    ``option[]`` children. Returning both shapes lets callers resolve the
    candidate summary IDs without caring which shape the server used.
    """
    out: list[dict[str, object]] = []
    for entry in dictionary_section_entries(raw_records, "activityArea"):
        out.append(entry)
        options = entry.get("option")
        if isinstance(options, list):
            out.extend(e for e in options if isinstance(e, dict))
    return out


def dictionary_contract_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract contract type entries from a BoondManager dictionary payload.

    Handles the nested shape ``setting.typeOf.contract[]``.
    """
    out: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        # Flat shape: direct "typeOf" list or "contract" list
        for key in ("contract", "typeOf"):
            value = record.get(key)
            if isinstance(value, list):
                out.extend(e for e in value if isinstance(e, dict))
        # BoondManager shape: setting.typeOf.contract[]
        setting = record.get("setting")
        if isinstance(setting, dict):
            for key in ("contract", "contracts"):
                value = setting.get(key)
                if isinstance(value, list):
                    out.extend(e for e in value if isinstance(e, dict))
            type_of = setting.get("typeOf")
            if isinstance(type_of, list):
                out.extend(e for e in type_of if isinstance(e, dict))
            if isinstance(type_of, dict):
                contract_list = type_of.get("contract") or type_of.get("contracts")
                if isinstance(contract_list, list):
                    out.extend(e for e in contract_list if isinstance(e, dict))
    return out


# Labels in candidate states that indicate the profile should be excluded
# from search results. Checked case-insensitively as substrings.
_EXCLUDED_STATE_KEYWORDS: Final[tuple[str, ...]] = (
    "ne plus contacter",
    "à supprimer",
    "a supprimer",
    "supprimer",
    "blacklist",
    "exclu",
    "do not contact",
    "to delete",
    "to be deleted",
    "désactivé",
    "desactive",
)


def dictionary_candidate_state_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract candidate state entries from a BoondManager dictionary payload.

    Handles the nested BoondManager shape ``setting.state.candidate[]``
    as well as simpler flat shapes used in older or mock servers.
    """
    out: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        # Flat shapes
        for key in ("state", "candidateStates", "candidate_states"):
            value = record.get(key)
            if isinstance(value, list):
                out.extend(e for e in value if isinstance(e, dict))
        # BoondManager shape: setting.state.candidate[]
        setting = record.get("setting")
        if isinstance(setting, dict):
            state_section = setting.get("state")
            if isinstance(state_section, dict):
                candidate_list = state_section.get("candidate")
                if isinstance(candidate_list, list):
                    out.extend(e for e in candidate_list if isinstance(e, dict))
            # Fallback: setting.candidateState[]
            for key in ("candidateState", "state"):
                value = setting.get(key)
                if isinstance(value, list):
                    out.extend(e for e in value if isinstance(e, dict))
    return out


def resolve_label_for_id(entries: Iterable[object], target_id: object) -> str | None:
    """Resolve a dictionary entry id to its human-readable label.

    Returns ``None`` when the id is not found in the entries.
    """
    if target_id in (None, ""):
        return None
    target = str(target_id).strip()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        eid = entry_id_of(entry)
        if eid is None or str(eid).strip() != target:
            continue
        return _label_of(entry)
    return None


def dictionary_availability_entries(
    raw_records: Iterable[object],
) -> list[dict[str, object]]:
    """Extract availability type entries from a BoondManager dictionary.

    Handles ``setting.availability[]`` (nested) and flat shapes.
    """
    out: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        direct = record.get("availability")
        if isinstance(direct, list):
            out.extend(e for e in direct if isinstance(e, dict))
        setting = record.get("setting")
        if isinstance(setting, dict):
            nested = setting.get("availability")
            if isinstance(nested, list):
                out.extend(e for e in nested if isinstance(e, dict))
    return out


def resolve_excluded_state_ids(entries: Iterable[object]) -> list[object]:
    """Return IDs of candidate states that indicate the profile should be excluded.

    Matches known "do not contact" / "to delete" keywords in state labels.
    Returns an empty list when no excluded states are identified (fail-open —
    never over-filters when the dictionary structure is unexpected).
    """
    excluded: list[object] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = _label_of(entry)
        entry_id = entry_id_of(entry)
        if entry_id is None or label is None:
            continue
        label_lower = label.lower()
        if any(kw in label_lower for kw in _EXCLUDED_STATE_KEYWORDS):
            excluded.append(entry_id)
    return excluded


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
        entry_id = entry_id_of(entry)
        if entry_id is None:
            continue
        candidates.append((threshold, entry_id))

    if not candidates:
        return None
    # Highest matching threshold wins — most specific bucket.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
