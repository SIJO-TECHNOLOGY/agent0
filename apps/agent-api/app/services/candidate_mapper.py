"""Normalize MCP `SearchResult` records into UI-friendly `CandidateCard`s.

The frontend must never consume raw MCP or BoondManager payloads.
This module is the single normalization layer: missing scalar fields
become ``None``, missing list fields become ``[]``, and we never
invent values that weren't grounded in the MCP result.

Only generic MCP field-name conventions are checked here — no
BoondManager API logic, no direct provider calls.
"""

from __future__ import annotations

import re
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

# Genuine years-of-experience fields ONLY. The bare BoondManager
# `experience` field is a dictionary LEVEL id (e.g. 3 = a seniority
# bucket), NOT a count of years, so it must never be shown as literal
# years. We surface experience_years only when a real year count exists.
_EXPERIENCE_FIELDS: Final[tuple[str, ...]] = (
    "experienceYears",
    "yearsOfExperience",
    "experience_years",
)

_CITY_FIELDS: Final[tuple[str, ...]] = ("city", "town", "locality")
_COUNTRY_FIELDS: Final[tuple[str, ...]] = ("country", "countryName")
_ADDRESS_FIELDS: Final[tuple[str, ...]] = ("address", "location")

_AVAILABILITY_FIELDS: Final[tuple[str, ...]] = (
    "_availabilityLabel",   # resolved by nodes.py from the BoondManager dictionary
    "availabilityLabel",
    "availability",
)
_AVAILABILITY_DATE_FIELDS: Final[tuple[str, ...]] = (
    "availabilityDate",
    "availableFrom",
    "available_from",
    "nextAvailability",
)
_EXPERIENCE_LABEL_FIELDS: Final[tuple[str, ...]] = (
    "_experienceLabel",     # resolved by nodes.py from the BoondManager dictionary
    "experienceLabel",
    "experience_label",
)
_STATE_LABEL_FIELDS: Final[tuple[str, ...]] = (
    "_stateLabel",
    "stateLabel",
    "state_label",
)

_SKILLS_FIELDS: Final[tuple[str, ...]] = (
    "skills",
    "technicalSkills",
    "technical_skills",
    "tags",
)
# Fields holding tool/technology proficiency entries (list of {tool, level}).
_TOOLS_FIELDS: Final[tuple[str, ...]] = ("tools", "technologies")
_LANGUAGES_FIELDS: Final[tuple[str, ...]] = ("languages",)
_DIPLOMAS_FIELDS: Final[tuple[str, ...]] = ("diplomas", "degrees")
_EXPERTISE_AREA_FIELDS: Final[tuple[str, ...]] = (
    "expertiseAreas",
    "expertise_areas",
)
_ACTIVITY_AREA_FIELDS: Final[tuple[str, ...]] = (
    "_resolvedActivityAreaLabels",
    "activityAreas",
    "activity_areas",
)
# Split a free-text skills string into discrete skills (delimiters only —
# never spaces, so multi-word skills like "machine learning" survive).
_SKILL_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[,;/|\n·•]+")
_MAX_SKILLS: Final[int] = 40
# Skills items split from free-text that are longer than this are descriptive
# sentences rather than skill tags. We filter them out to avoid showing
# "capacité à sécuriser les mises en production" as a skill name.
_MAX_SKILL_ITEM_LENGTH: Final[int] = 40
_SKILL_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "jobTitle",
    "headline",
    "position",
    "role",
    "snippet",
    "summary",
    "description",
    # NOTE: "_resumeText" is intentionally absent — it is always processed
    # as a dedicated step in _extract_skills regardless of whether other
    # structured skills were found, so it must not be treated as a fallback.
)
_KNOWN_SKILL_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # Languages
    (r"\bjava\b", "Java"),
    (r"\bj2ee\b", "J2EE"),
    (r"\bc\+\+", "C++"),
    (r"\bc#\b", "C#"),
    (r"\bpython\b", "Python"),
    (r"\bphp\b", "PHP"),
    (r"\b\.net\b", ".NET"),
    (r"\bscala\b", "Scala"),
    (r"\bkotlin\b", "Kotlin"),
    (r"\brust\b", "Rust"),
    (r"\bgo\b|\bgolang\b", "Go"),
    (r"\bswift\b", "Swift"),
    (r"\btyescript\b|\bts\b", "TypeScript"),
    (r"\bjavascript\b|\bjs\b", "JavaScript"),
    # Frameworks / libs
    (r"\bspring\s*boot\b", "Spring Boot"),
    (r"\bspring\b", "Spring"),
    (r"\bhibernate\b", "Hibernate"),
    (r"\bjsp\b", "JSP"),
    (r"\bjsf\b", "JSF"),
    (r"\bstruts\b", "Struts"),
    (r"\bangular\b", "Angular"),
    (r"\breact\b", "React"),
    (r"\bvue\b", "Vue.js"),
    (r"\bnode(?:\.js)?\b", "Node.js"),
    (r"\bdjango\b", "Django"),
    (r"\bflask\b", "Flask"),
    # Data / messaging
    (r"\bkafka\b", "Kafka"),
    (r"\brabbit\s*mq\b", "RabbitMQ"),
    (r"\belastic\s*search\b|\belasticsearch\b", "Elasticsearch"),
    (r"\bspark\b", "Spark"),
    (r"\bhadoop\b", "Hadoop"),
    # Databases
    (r"\bsql\b", "SQL"),
    (r"\bpostgre\b|\bpostgresql\b", "PostgreSQL"),
    (r"\bmysql\b", "MySQL"),
    (r"\boracle\b", "Oracle"),
    (r"\bmongo\s*db\b|\bmongodb\b", "MongoDB"),
    (r"\bredis\b", "Redis"),
    # Infrastructure / cloud
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\baws\b", "AWS"),
    (r"\bazure\b", "Azure"),
    (r"\bgcp\b|\bgoogle\s*cloud\b", "GCP"),
    (r"\bjenkins\b", "Jenkins"),
    (r"\bci\s*/\s*cd\b|\bcicd\b", "CI/CD"),
    (r"\bdevops\b", "DevOps"),
    (r"\bterraform\b", "Terraform"),
    # Finance / domain
    (r"\bfixe[sd]?\s*income\b|\bobligations?\b", "Produits de taux"),
    (r"\bderivativ[esi]+\b|\bderivés?\b", "Dérivés"),
    (r"\bmarket\s*data\b", "Market Data"),
    (r"\bfrontoffice\b|\bfront\s*office\b", "Front Office"),
    (r"\bmiddleoffice\b|\bmiddle\s*office\b", "Middle Office"),
    (r"\brisque?\b|\brisk\b", "Gestion du risque"),
    (r"\btrading\b", "Trading"),
    (r"\bbloomberg\b", "Bloomberg"),
    (r"\breuters\b|\brefinitiv\b", "Reuters/Refinitiv"),
    # Frontend
    (r"\bfront[-\s]?end\b", "Front-end"),
    (r"\bback[-\s]?end\b", "Back-end"),
    (r"\bmicroservice", "Microservices"),
    (r"\bapi\s*rest\b|\brestful\b|\brest\s*api\b", "REST API"),
    (r"\bsoap\b", "SOAP"),
    (r"\bxml\b", "XML"),
    (r"\bjson\b", "JSON"),
    (r"\bgit\b", "Git"),
    (r"\bscrum\b|\bagile\b", "Agile/Scrum"),
    (r"\bjira\b", "Jira"),
)

_BOOND_URL_FIELDS: Final[tuple[str, ...]] = ("boondUrl", "boond_url", "url", "link")
_HIGHLIGHTS_FIELDS: Final[tuple[str, ...]] = (
    "highlights",
    "matchedKeywords",
    "matched_keywords",
    "keywordsMatched",
)
_EXPERIENCES_FIELDS: Final[tuple[str, ...]] = (
    "experiences",
    "workHistory",
    "work_history",
    "recentExperiences",
    "career",
)
_CONTRACT_FIELDS: Final[tuple[str, ...]] = (
    "_contractLabel",       # resolved from BoondManager dictionary (setting.typeOf.contract)
    "contractPreferences",
    "contract_preferences",
    "contractType",
    "contractLabel",
    "typeOf",               # raw BoondManager field name for contract type
    "contract",
)
_SALARY_FIELDS: Final[tuple[str, ...]] = (
    "salaryExpectation",
    "salary_expectation",
    "expectedSalary",
    "currentSalary",    # from getCandidateAdministrative
    "minSalary",        # from getCandidateAdministrative
    "salary",
)
_TJM_FIELDS: Final[tuple[str, ...]] = (
    "tjm",
    "dailyRate",
    "daily_rate",
    "tjmExpected",
    "currentDailyRate",  # from getCandidateAdministrative
    "minDailyRate",      # from getCandidateAdministrative
)
_MOBILITY_FIELDS: Final[tuple[str, ...]] = (
    "_mobilityLabel",     # resolved from BoondManager dictionary option IDs
    "mobility",
    "mobilityLabel",
    "mobilityZone",
    # NOTE: mobilityAreas raw list is handled separately in _build_mobility
)
_STRENGTHS_FIELDS: Final[tuple[str, ...]] = ("strengths", "strongPoints", "strong_points")
_WATCH_POINTS_FIELDS: Final[tuple[str, ...]] = (
    "watchPoints",
    "watch_points",
    "vigilancePoints",
    "vigilance_points",
    "weaknesses",
)
_AI_EVALUATION_FIELDS: Final[tuple[str, ...]] = (
    "aiEvaluation",
    "ai_evaluation",
    "matchExplanation",
    "match_explanation",
)
_SOURCE_FIELDS: Final[tuple[str, ...]] = (
    "_sourceLabel",
    "sourceLabel",
    "sourceDetail",
    "source",
    "creationSource",
)
_UPDATE_FIELDS: Final[tuple[str, ...]] = (
    "updateDate",
    "updatedAt",
    "lastUpdate",
    "last_action_date",
)
_TECHNICAL_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "technicalSummary",
    "technical_summary",
    "summary",
    "description",
)
_ENRICHMENT_FIELDS: Final[tuple[str, ...]] = (
    "_enrichment_detail",
    "_enrichment_technical_document",
    "_enrichment_resume",
    "_enrichment_administrative",
)
_SAFE_INTERNAL_FIELDS: Final[tuple[str, ...]] = (
    "_availabilityLabel",
    "_experienceLabel",
    "_contractLabel",
    "_mobilityLabel",
    "_resolvedToolLabels",
    "_stateLabel",
    "_resolvedLanguageLabels",
    "_resolvedActivityAreaLabels",
    "_sourceLabel",
)

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
    technical_document = flat.get("technicalDocument")
    if isinstance(technical_document, dict):
        for key, value in technical_document.items():
            flat.setdefault(key, value)
        # NOTE: the BoondManager `experience` field is a LEVEL ID (e.g. 5 = "10+ ans"),
        # NOT a count of years. Never store it in experienceYears — the label resolver
        # in nodes.py handles human-readable display via _experienceLabel.
        # Only use it if the dict already has a genuine year count field.
    # For the technical document, merge list fields (skills, tools) rather than
    # setdefault — the DT is the authoritative source for skill data.
    _MERGE_FROM_TECH_DOC = {
        "tools",
        "technologies",
        "skills",
        "tags",
        "languages",
        "diplomas",
        "expertiseAreas",
        "activityAreas",
    }
    for enrichment_key in _ENRICHMENT_FIELDS:
        enrichment = flat.get(enrichment_key)
        if not isinstance(enrichment, dict):
            continue
        is_tech_doc = enrichment_key == "_enrichment_technical_document"
        is_resume = enrichment_key == "_enrichment_resume"

        is_administrative = enrichment_key == "_enrichment_administrative"

        if is_resume:
            # The CV enrichment carries the raw extracted PDF text.
            # Surface it as a searchable text field and extract skill hints.
            generated_summary = enrichment.get("generatedSummary")
            if isinstance(generated_summary, str) and generated_summary.strip():
                flat["_resumeGeneratedSummary"] = generated_summary.strip()
            cv_text = enrichment.get("extractedText") or enrichment.get("text") or ""
            if isinstance(cv_text, str) and cv_text.strip():
                flat.setdefault("_resumeText", cv_text.strip())
                # Use the CV text as a summary fallback if nothing better exists.
                if not flat.get("summary") and len(cv_text) > 20:
                    flat.setdefault("summary", cv_text[:500].strip())
            continue

        if is_administrative:
            # Convert numeric salary/TJM fields to formatted strings so
            # _first_non_empty_str can pick them up downstream.
            for field in (
                "currentDailyRate", "minDailyRate", "maxDailyRate",
                "currentSalary", "minSalary", "maxSalary",
            ):
                raw_val = enrichment.get(field)
                if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool) and raw_val > 0:
                    formatted = f"{int(raw_val)} €" if raw_val == int(raw_val) else f"{raw_val:.2f} €"
                    flat.setdefault(field, formatted)
                elif isinstance(raw_val, str) and raw_val.strip():
                    flat.setdefault(field, raw_val.strip())
            continue

        for key, value in enrichment.items():
            if is_tech_doc and key in _MERGE_FROM_TECH_DOC and isinstance(value, (list, str)):
                existing = flat.get(key)
                if existing is None:
                    flat[key] = value
                elif isinstance(value, list) and isinstance(existing, list):
                    # Combine: tech doc entries first (more authoritative), then existing.
                    seen = {str(item) for item in value}
                    extra = [item for item in existing if str(item) not in seen]
                    flat[key] = list(value) + extra
                elif isinstance(value, str) and isinstance(existing, str):
                    # Concatenate free-text skill strings.
                    if value.strip() and value.strip() not in existing:
                        flat[key] = f"{value}, {existing}"
                elif isinstance(value, list):
                    flat[key] = value
            elif is_tech_doc and key == "summary" and isinstance(value, str) and value.strip():
                # Prefer tech doc summary — it's the curated professional description.
                flat[key] = value
            elif is_tech_doc and key == "description" and isinstance(value, str) and value.strip():
                flat.setdefault("summary", value)
            else:
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


def _is_raw_integer(value: str) -> bool:
    """Return True when the value is a bare integer (a raw BoondManager ID)."""
    try:
        int(value.strip())
        return True
    except ValueError:
        return False


def _build_mobility(data: dict[str, object]) -> str | None:
    """Return a human-readable mobility string.

    Tries structured label fields first, then falls back to joining the
    ``mobilityAreas`` list that BoondManager returns from searchCandidates.
    """
    label = _first_non_empty_str(data, _MOBILITY_FIELDS)
    if label and not _is_raw_integer(label):
        return label
    areas = data.get("mobilityAreas")
    if isinstance(areas, list) and areas:
        parts = [str(a).strip() for a in areas if a and str(a).strip()]
        if parts:
            return ", ".join(parts[:3])
    return None


def _build_availability(data: dict[str, object]) -> str | None:
    label = _first_non_empty_str(data, _AVAILABILITY_FIELDS)
    if label:
        # Don't surface raw BoondManager integer availability type IDs (e.g. "-1", "3").
        if _is_raw_integer(label):
            label = None
        else:
            return label
    date = _first_non_empty_str(data, _AVAILABILITY_DATE_FIELDS)
    if date and not _is_raw_integer(date):
        return f"Disponible à partir du {date}"
    return None


def _build_experience_label(data: dict[str, object]) -> str | None:
    """Return the resolved experience level label if available."""
    return _first_non_empty_str(data, _EXPERIENCE_LABEL_FIELDS)


def _extract_skills(data: dict[str, object]) -> list[str]:
    """Collect candidate skills from BoondManager summary + technical doc.

    Handles the real shapes: a free-text ``skills`` STRING (split on
    delimiters), list skills, and the ``tools`` proficiency list of
    ``{tool, level}`` dicts. De-duplicated, order-preserving, capped.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str, *, enforce_length: bool = True) -> None:
        text = value.strip()
        key = text.lower()
        if (
            text
            and key not in seen
            and len(out) < _MAX_SKILLS
            and (not enforce_length or len(text) <= _MAX_SKILL_ITEM_LENGTH)
        ):
            seen.add(key)
            out.append(text)

    # Resolved tool labels (IDs like "ccc"→"C++", "act"→"React" already resolved).
    resolved_tools = data.get("_resolvedToolLabels")
    if isinstance(resolved_tools, list):
        for name in resolved_tools:
            if isinstance(name, str):
                _add(name, enforce_length=False)

    # Structured tool/technology proficiency first (most reliable).
    # Tool names from the DT are always short labels → no length enforcement needed.
    for key in _TOOLS_FIELDS:
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    _add(item, enforce_length=False)
                elif isinstance(item, dict):
                    name = _first_non_empty_str(item, ("tool", "name", "label", "skill"))
                    if name:
                        _add(name, enforce_length=False)

    # Skills text / list fields.
    # Length filter applied: BoondManager's free-text skills field often contains
    # sentences (e.g. "capacité à sécuriser les mises en production") — we drop
    # anything over _MAX_SKILL_ITEM_LENGTH chars, keeping only true skill names.
    for key in _SKILLS_FIELDS:
        value = data.get(key)
        if isinstance(value, str):
            for part in _SKILL_SPLIT_RE.split(value):
                _add(part)  # enforce_length=True filters long sentences
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    _add(item)
                elif isinstance(item, dict):
                    name = _first_non_empty_str(item, ("name", "label", "skill", "tool"))
                    if name:
                        _add(name)

    # Fallback: when no structured skills exist, infer from short text fields
    # (title, snippet, summary). Only used when the structured sources above
    # returned nothing — avoids noise when richer data is already present.
    if not out:
        for inferred in _infer_skills_from_text(data):
            _add(inferred)

    # ALWAYS scan description and summary for skills — these often contain
    # the tech doc's free-text profile which is richer than the structured
    # fields (e.g. "Développeur C++/C#, Java, Finance de marché...").
    # Pattern-matched labels are always short → no length enforcement needed.
    for text_key in ("description", "summary", "snippet"):
        text_val = data.get(text_key)
        if isinstance(text_val, str) and text_val.strip():
            for pattern, label in _KNOWN_SKILL_PATTERNS:
                if re.search(pattern, text_val, flags=re.IGNORECASE):
                    _add(label, enforce_length=False)

    # ALWAYS extract from CV PDF text regardless of other sources.
    resume_text = data.get("_resumeText")
    if isinstance(resume_text, str) and resume_text.strip():
        for pattern, label in _KNOWN_SKILL_PATTERNS:
            if re.search(pattern, resume_text, flags=re.IGNORECASE):
                _add(label, enforce_length=False)

    return out


def _infer_skills_from_text(data: dict[str, object]) -> list[str]:
    """Extract visible skill tags from Boond-returned text fields only."""
    haystack = " ".join(
        value.strip()
        for key in _SKILL_TEXT_FIELDS
        if isinstance((value := data.get(key)), str) and value.strip()
    )
    if not haystack:
        return []

    skills: list[str] = []
    for pattern, label in _KNOWN_SKILL_PATTERNS:
        if re.search(pattern, haystack, flags=re.IGNORECASE) and label not in skills:
            skills.append(label)
    return skills[:20]


def _extract_string_list(data: dict[str, object], keys: Iterable[str]) -> list[str]:
    """Extract the first non-empty string list found under any of the given keys."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            result = [
                str(item).strip()
                for item in value
                if item is not None
                and isinstance(item, (str, int, float))
                and not isinstance(item, bool)
                and str(item).strip()
            ]
            if result:
                return result
        if isinstance(value, str) and value.strip():
            return [s.strip() for s in _SKILL_SPLIT_RE.split(value) if s.strip()]
    return []


def _extract_named_entries(
    data: dict[str, object],
    keys: Iterable[str],
    *,
    name_fields: tuple[str, ...],
    label_name: str,
    level_fields: tuple[str, ...] = ("level",),
    label_level: str = "level",
) -> list[dict[str, object]]:
    """Extract list entries shaped for the frontend, preserving levels."""
    for key in keys:
        value = data.get(key)
        if not isinstance(value, list) or not value:
            continue
        result: list[dict[str, object]] = []
        seen: set[tuple[str, str | None]] = set()
        for item in value:
            if isinstance(item, str) and item.strip():
                name = item.strip()
                level = None
            elif isinstance(item, dict):
                name = _first_non_empty_str(item, name_fields)
                level = _first_non_empty_str(item, level_fields)
                if level is None:
                    raw_level = next(
                        (
                            item.get(field)
                            for field in level_fields
                            if item.get(field) not in (None, "")
                        ),
                        None,
                    )
                    if isinstance(raw_level, (int, float)) and not isinstance(raw_level, bool):
                        level = str(raw_level)
            else:
                continue
            if not name:
                continue
            dedupe_key = (name.lower(), level.lower() if isinstance(level, str) else None)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entry: dict[str, object] = {label_name: name}
            if level:
                entry[label_level] = level
            result.append(entry)
        if result:
            return result
    return []


def _extract_tools(data: dict[str, object]) -> list[dict[str, object]]:
    resolved = data.get("_resolvedToolLabels")
    if isinstance(resolved, list) and resolved:
        raw_tools = data.get("tools")
        levels_by_raw_name: dict[str, object] = {}
        if isinstance(raw_tools, list):
            for item in raw_tools:
                if isinstance(item, dict):
                    raw_name = _first_non_empty_str(item, ("tool", "name", "label", "skill"))
                    if raw_name and item.get("level") not in (None, ""):
                        levels_by_raw_name[raw_name.lower()] = item.get("level")
        result: list[dict[str, object]] = []
        for label in resolved:
            if not isinstance(label, str) or not label.strip():
                continue
            entry: dict[str, object] = {"name": label.strip()}
            level = levels_by_raw_name.get(label.strip().lower())
            if level not in (None, ""):
                entry["level"] = level
            result.append(entry)
        if result:
            return result
    return _extract_named_entries(
        data,
        _TOOLS_FIELDS,
        name_fields=("tool", "name", "label", "skill"),
        label_name="name",
    )


def _extract_languages(data: dict[str, object]) -> list[dict[str, object]]:
    resolved = data.get("_resolvedLanguageLabels")
    if isinstance(resolved, list) and resolved:
        return [dict(item) for item in resolved if isinstance(item, dict)]
    return _extract_named_entries(
        data,
        _LANGUAGES_FIELDS,
        name_fields=("language", "name", "label"),
        label_name="language",
        level_fields=("level", "levelLabel"),
    )


def _build_technical_summary(data: dict[str, object]) -> str | None:
    tech = data.get("_enrichment_technical_document")
    if isinstance(tech, dict):
        summary = _first_non_empty_str(tech, _TECHNICAL_SUMMARY_FIELDS)
        if summary:
            return summary
    summary = _first_non_empty_str(data, ("technicalSummary", "technical_summary"))
    if summary:
        return summary
    generated = _first_non_empty_str(data, ("_resumeGeneratedSummary",))
    if generated:
        return generated
    return _extract_resume_profile_summary(data)


def _extract_experiences(data: dict[str, object]) -> list[dict[str, object]]:
    """Extract recent experiences as normalized {title, company, period} dicts."""
    for key in _EXPERIENCES_FIELDS:
        value = data.get(key)
        if not isinstance(value, list) or not value:
            continue
        result: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            title = _first_non_empty_str(item, ("title", "jobTitle", "position", "role"))
            company = _first_non_empty_str(item, ("company", "employer", "organization", "client"))
            period = _first_non_empty_str(item, ("period", "dates", "duration", "startDate"))
            if title or company:
                result.append({"title": title, "company": company, "period": period})
        if result:
            return result[:5]
    return []


def _extract_ai_evaluation(data: dict[str, object]) -> dict[str, object] | None:
    """Return the AI evaluation block verbatim if it is a non-empty dict."""
    for key in _AI_EVALUATION_FIELDS:
        value = data.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def _build_boond_url(
    data: dict[str, object],
    *,
    resolved_id: str | None = None,
    boond_base_url: str = "https://ui.boondmanager.com",
) -> str | None:
    candidate_url = _first_non_empty_str(data, _BOOND_URL_FIELDS)
    if candidate_url and candidate_url.startswith(("http://", "https://")):
        return candidate_url
    # BoondManager's API doesn't return a direct URL — construct it from the ID.
    if resolved_id:
        return f"{boond_base_url.rstrip('/')}/candidates/{resolved_id}/overview"
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
    generated = _first_non_empty_str(data, ("_resumeGeneratedSummary",))
    if generated:
        return generated

    resume_summary = _extract_resume_profile_summary(data)
    if resume_summary:
        return resume_summary

    snippet = _first_non_empty_str(data, ("snippet", "summary", "description"))
    if snippet:
        return snippet
    if full_name and title:
        return f"{full_name} - {title}."
    if full_name:
        return f"Profil candidat : {full_name}."
    if title:
        return f"Candidat correspondant au profil : {title}."
    return "Profil candidat trouvé dans BoondManager."


def _extract_resume_profile_summary(data: dict[str, object]) -> str | None:
    """Extract a concise profile synthesis from the parsed CV PDF text."""
    resume_text = data.get("_resumeText")
    if not isinstance(resume_text, str) or not resume_text.strip():
        return None

    normalized = re.sub(r"\r\n?", "\n", resume_text.strip())
    limit = 260
    patterns = (
        r"(?is)\bsynth[eè]se\s+de\s+profil\b\s*(.+?)(?=\n\s*(?:comp[eé]tences|exp[eé]rience|formation|dipl[oô]mes?|langues?|outils?|missions?)\b)",
        r"(?is)\bprofil\b\s*(.+?)(?=\n\s*(?:comp[eé]tences|exp[eé]rience|formation|dipl[oô]mes?|langues?|outils?|missions?)\b)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            summary = _compact_resume_text(match.group(1), limit=limit)
            if summary:
                return summary

    professional_lines = [
        _clean_resume_summary_line(line)
        for line in normalized.split("\n")
        if _is_resume_summary_line(line) and _looks_like_profile_line(line)
    ]
    profile_summary = _summary_from_lines(professional_lines, limit=limit)
    if profile_summary:
        return profile_summary

    lines = [
        _clean_resume_summary_line(line)
        for line in normalized.split("\n")
        if _is_resume_summary_line(line)
    ]
    return _summary_from_lines(lines, limit=limit)


def _summary_from_lines(lines: list[str], *, limit: int) -> str | None:
    summary_parts: list[str] = []
    for line in lines[:8]:
        summary_parts.append(line)
        compact = _compact_resume_text(" ".join(summary_parts), limit=limit)
        if compact and len(compact) >= 120:
            return compact
    if summary_parts:
        return _compact_resume_text(" ".join(summary_parts), limit=limit)
    return None


def _is_resume_summary_line(value: str) -> bool:
    text = _clean_resume_summary_line(value)
    if len(text) < 25:
        return False
    if re.search(r"@|linkedin|github\.com|^\+?\d|www\.|https?://", text, flags=re.IGNORECASE):
        return False
    if re.search(
        r"\b(native or bilingual|professional working|full professional|limited working|toeic|certified|certification)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if re.search(
        r"^(coordonn[eé]es|contact|r[eé]seaux sociaux|langues?|languages?|principales comp[eé]tences|comp[eé]tences|formation|education|exp[eé]rience)$",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _clean_resume_summary_line(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip(" -:;")
    text = re.sub(
        r"\bERROR!\s*UNKNOWN\s+DOCUMENT\s+PROPERTY\s+NAME\.?\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bAdresse\s*:.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:;")
    return text


def _looks_like_profile_line(value: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"analyst|analyste|application owner|business|consultant|developer|"
            r"d[eé]veloppeur|engineer|ing[eé]nieur|architect|software|data|"
            r"product owner|scrum|chef de projet|project manager|lead|manager"
            r")\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _compact_resume_text(value: str, *, limit: int = 260) -> str | None:
    text = re.sub(r"\s+", " ", value).strip(" -:;")
    if len(text) < 40:
        return None
    return _truncate_text(text, limit)


def _truncate_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    truncated = text[: limit - 1].rsplit(" ", 1)[0].strip()
    return f"{truncated}..."


def candidate_card_from_result(
    result: SearchResult,
    *,
    boond_base_url: str = "https://ui.boondmanager.com",
) -> CandidateCard | None:
    """Map a single search result to a UI-shaped candidate card.

    Returns ``None`` when the underlying MCP record carried no usable
    candidate id. The caller should drop such records rather than
    surfacing a fake "unknown" candidate to the frontend.
    """
    # Drop internal markers (e.g. enrichment flags) from lookups.
    safe_data = {
        k: v
        for k, v in result.data.items()
        if (
            (isinstance(k, str) and k in _ENRICHMENT_FIELDS)
            or (isinstance(k, str) and k in _SAFE_INTERNAL_FIELDS)
            or not (isinstance(k, str) and k.startswith(_INTERNAL_DATA_PREFIXES))
        )
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
        experience_label=_build_experience_label(merged),
        location=_build_location(merged),
        availability=_build_availability(merged),
        skills=_extract_skills(merged),
        match_score=_match_score(result),
        summary=_build_summary(full_name, title, merged),
        boond_url=_build_boond_url(merged, resolved_id=resolved_id, boond_base_url=boond_base_url),
        highlights=_extract_string_list(merged, _HIGHLIGHTS_FIELDS),
        experiences=_extract_experiences(merged),
        ai_evaluation=_extract_ai_evaluation(merged),
        contract_preferences=_extract_string_list(merged, _CONTRACT_FIELDS),
        salary_expectation=_first_non_empty_str(merged, _SALARY_FIELDS),
        tjm=_first_non_empty_str(merged, _TJM_FIELDS),
        mobility=_build_mobility(merged),
        strengths=_extract_string_list(merged, _STRENGTHS_FIELDS),
        watch_points=_extract_string_list(merged, _WATCH_POINTS_FIELDS),
        state_label=_first_non_empty_str(merged, _STATE_LABEL_FIELDS),
        source=_first_non_empty_str(merged, _SOURCE_FIELDS),
        last_update=_first_non_empty_str(merged, _UPDATE_FIELDS),
        technical_summary=_build_technical_summary(merged),
        diplomas=_extract_string_list(merged, _DIPLOMAS_FIELDS),
        expertise_areas=_extract_string_list(merged, _EXPERTISE_AREA_FIELDS),
        activity_areas=_extract_string_list(merged, _ACTIVITY_AREA_FIELDS),
        tools=_extract_tools(merged),
        languages=_extract_languages(merged),
    )


def candidate_cards_from_results(
    results: Iterable[SearchResult],
    *,
    boond_base_url: str = "https://ui.boondmanager.com",
) -> list[CandidateCard]:
    cards: list[CandidateCard] = []
    for result in results:
        card = candidate_card_from_result(result, boond_base_url=boond_base_url)
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
    *,
    boond_base_url: str = "https://ui.boondmanager.com",
) -> tuple[list[CandidateCard], list[dict[str, object]]]:
    """Map SearchResults to CandidateCards while collecting drop diagnostics."""
    cards: list[CandidateCard] = []
    dropped: list[dict[str, object]] = []
    for result in results:
        card = candidate_card_from_result(result, boond_base_url=boond_base_url)
        if card is None:
            dropped.append(diagnose_dropped_record(result))
        else:
            cards.append(card)
    return cards, dropped


def candidate_full_name(result: SearchResult) -> str | None:
    """Best-effort display name for a search result.

    Reuses the same name resolution the card mapper uses, so ranking and the
    rendered card agree on a candidate's name.
    """
    return _build_full_name(_flatten_record(dict(result.data)))
