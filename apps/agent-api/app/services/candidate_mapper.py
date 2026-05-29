"""Normalize MCP `SearchResult` records into UI-friendly `CandidateCard`s.

The frontend must never consume raw MCP or BoondManager payloads.
This module is the single normalization layer: missing scalar fields
become ``None``, missing list fields become ``[]``, and we never
invent values that weren't grounded in the MCP result.

Only generic MCP field-name conventions are checked here — no
BoondManager API logic, no direct provider calls.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from app.models.api import CandidateCard
from app.models.results import SearchResult

# Tool name prefixes that, by MCP convention, return a relevance score.
# Detail-style lookups (e.g. ``getCandidateDetail``) do not, so their
# synthesized internal score (1.0) must surface as ``None`` to the UI.
_SCORED_TOOL_PREFIXES: Final[tuple[str, ...]] = ("search",)

_NAME_FIELDS_FIRST: Final[tuple[str, ...]] = ("firstName", "first_name", "givenName")
_NAME_FIELDS_LAST: Final[tuple[str, ...]] = ("lastName", "last_name", "familyName")
_NAME_FIELDS_FULL: Final[tuple[str, ...]] = ("fullName", "full_name", "name")

_TITLE_FIELDS: Final[tuple[str, ...]] = (
    "jobTitle",
    "title",
    "headline",
    "position",
    "role",
)

_EXPERIENCE_FIELDS: Final[tuple[str, ...]] = (
    "experienceYears",
    "yearsOfExperience",
    "experience_years",
    "experience",
)

_CITY_FIELDS: Final[tuple[str, ...]] = ("city", "town", "locality")
_COUNTRY_FIELDS: Final[tuple[str, ...]] = ("country", "countryName")
_ADDRESS_FIELDS: Final[tuple[str, ...]] = ("address", "location")

_AVAILABILITY_FIELDS: Final[tuple[str, ...]] = (
    "availability",
    "availabilityLabel",
)
_AVAILABILITY_DATE_FIELDS: Final[tuple[str, ...]] = (
    "availabilityDate",
    "availableFrom",
    "available_from",
    "nextAvailability",
)

_SKILLS_FIELDS: Final[tuple[str, ...]] = (
    "skills",
    "technicalSkills",
    "technical_skills",
    "tags",
)

_BOOND_URL_FIELDS: Final[tuple[str, ...]] = ("boondUrl", "boond_url", "url", "link")

# Internal data keys we never surface in candidate cards.
_INTERNAL_DATA_PREFIXES: Final[tuple[str, ...]] = ("_",)


def _flatten_record(data: dict[str, object]) -> dict[str, object]:
    """Return a merged view that hoists JSON:API ``attributes`` to the top.

    BoondManager's MCP server commonly returns JSON:API-style records
    where most fields live under ``attributes``. We keep the original
    dict but expose its inner attributes alongside top-level keys so
    field lookups don't need to know which shape they got.

    Top-level keys win on conflict.
    """
    flat: dict[str, object] = dict(data)
    for nested_key in ("attributes", "data"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            for key, value in nested.items():
                flat.setdefault(key, value)
    return flat


# Candidate id field names we'll accept, in priority order. The
# candidate_mapper consults this list when ``_record_to_result``
# already failed at the canonical paths (top-level ``id`` and JSON:API
# ``attributes.id``), so a wider net is appropriate here.
_ID_FIELD_CANDIDATES: Final[tuple[str, ...]] = (
    "id",
    "candidateId",
    "candidate_id",
    "_id",
    "uuid",
    "guid",
    "key",
)


def _resolve_id(merged: dict[str, object], fallback: str) -> str | None:
    """Find a usable candidate id from merged data, else the fallback.

    Returns ``None`` only when no real id can be found anywhere — the
    mapper drops such candidates rather than emitting the literal
    string "unknown".
    """
    if fallback and fallback != "unknown":
        return fallback
    for field in _ID_FIELD_CANDIDATES:
        raw_id = merged.get(field)
        if raw_id in (None, "", "unknown", "null"):
            continue
        return str(raw_id)
    return None


def _first_non_empty_str(data: dict[str, object], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _first_number(data: dict[str, object], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):  # bool is a subclass of int; exclude.
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _build_full_name(data: dict[str, object]) -> str | None:
    full = _first_non_empty_str(data, _NAME_FIELDS_FULL)
    if full:
        return full
    first = _first_non_empty_str(data, _NAME_FIELDS_FIRST)
    last = _first_non_empty_str(data, _NAME_FIELDS_LAST)
    if first and last:
        return f"{first} {last}"
    return first or last


def _build_location(data: dict[str, object]) -> str | None:
    city = _first_non_empty_str(data, _CITY_FIELDS)
    country = _first_non_empty_str(data, _COUNTRY_FIELDS)
    if city and country:
        return f"{city}, {country}"
    if city or country:
        return city or country
    return _first_non_empty_str(data, _ADDRESS_FIELDS)


def _build_availability(data: dict[str, object]) -> str | None:
    label = _first_non_empty_str(data, _AVAILABILITY_FIELDS)
    if label:
        return label
    date = _first_non_empty_str(data, _AVAILABILITY_DATE_FIELDS)
    if date:
        return f"Available from {date}"
    return None


def _extract_skills(data: dict[str, object]) -> list[str]:
    for key in _SKILLS_FIELDS:
        value = data.get(key)
        if isinstance(value, list):
            skills: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    skills.append(item.strip())
                elif isinstance(item, dict):
                    name = _first_non_empty_str(item, ("name", "label", "skill"))
                    if name:
                        skills.append(name)
            if skills:
                return skills
    return []


def _build_boond_url(data: dict[str, object]) -> str | None:
    candidate_url = _first_non_empty_str(data, _BOOND_URL_FIELDS)
    if candidate_url and candidate_url.startswith(("http://", "https://")):
        return candidate_url
    return None


def _match_score(result: SearchResult) -> float | None:
    """Pass through the relevance score for search-style tools only.

    Detail-style tools (e.g. ``getCandidateDetail``) carry a synthesized
    internal score that is not a real relevance signal; surface as None.
    """
    if not any(result.source_tool.startswith(p) for p in _SCORED_TOOL_PREFIXES):
        return None
    if result.score <= 0.0:
        return None
    return result.score


def _build_summary(
    full_name: str | None, title: str | None, data: dict[str, object]
) -> str | None:
    snippet = _first_non_empty_str(data, ("snippet", "summary", "description"))
    if snippet:
        return snippet
    if full_name and title:
        return f"{full_name} — {title}."
    if full_name:
        return f"Candidate profile for {full_name}."
    if title:
        return f"Candidate matching: {title}."
    return "Candidate profile found in BoondManager."


def candidate_card_from_result(result: SearchResult) -> CandidateCard | None:
    """Map a single search result to a UI-shaped candidate card.

    Returns ``None`` when the underlying MCP record carried no usable
    candidate id. The caller should drop such records rather than
    surfacing a fake "unknown" candidate to the frontend.
    """
    # Drop internal markers (e.g. enrichment flags) from lookups.
    safe_data = {
        k: v
        for k, v in result.data.items()
        if not (isinstance(k, str) and k.startswith(_INTERNAL_DATA_PREFIXES))
    }
    merged: dict[str, object] = _flatten_record(safe_data)

    # Surface SearchResult-level scalars back into the lookup table.
    if result.title and "title" not in merged:
        merged["title"] = result.title
    if result.snippet and "snippet" not in merged:
        merged["snippet"] = result.snippet

    resolved_id = _resolve_id(merged, str(result.id) if result.id else "")
    if resolved_id is None:
        return None

    full_name = _build_full_name(merged)
    title = _first_non_empty_str(merged, _TITLE_FIELDS)
    # The fallback `title = id` from `_record_to_result` is internal —
    # don't surface it to the UI as a job title.
    if title and title.strip() == resolved_id.strip():
        title = None

    return CandidateCard(
        id=resolved_id,
        full_name=full_name,
        title=title,
        experience_years=_first_number(merged, _EXPERIENCE_FIELDS),
        location=_build_location(merged),
        availability=_build_availability(merged),
        skills=_extract_skills(merged),
        match_score=_match_score(result),
        summary=_build_summary(full_name, title, merged),
        boond_url=_build_boond_url(merged),
    )


def candidate_cards_from_results(
    results: Iterable[SearchResult],
) -> list[CandidateCard]:
    cards: list[CandidateCard] = []
    for result in results:
        card = candidate_card_from_result(result)
        if card is not None:
            cards.append(card)
    return cards


def _record_top_level_keys(result: SearchResult) -> list[str]:
    """Safe view of the record's top-level keys (sanitized, capped)."""
    keys = [
        str(k)
        for k in result.data.keys()
        if not (isinstance(k, str) and k.startswith("_"))
    ]
    return sorted(keys)[:25]


def diagnose_dropped_record(result: SearchResult) -> dict[str, object]:
    """Return a safe diagnostic dict explaining why a record was dropped.

    Exposes only structural information (top-level keys + source tool +
    a short human-readable reason). No values, no raw payload — safe
    for normal stream mode.
    """
    return {
        "source_tool": result.source_tool,
        "reason": "no resolvable candidate id found in record",
        "record_keys": _record_top_level_keys(result),
    }


def candidate_cards_with_diagnostics(
    results: Iterable[SearchResult],
) -> tuple[list[CandidateCard], list[dict[str, object]]]:
    """Map SearchResults to CandidateCards while collecting drop diagnostics."""
    cards: list[CandidateCard] = []
    dropped: list[dict[str, object]] = []
    for result in results:
        card = candidate_card_from_result(result)
        if card is None:
            dropped.append(diagnose_dropped_record(result))
        else:
            cards.append(card)
    return cards, dropped
