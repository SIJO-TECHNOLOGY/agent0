"""Agent1 — candidate data normalisation.

Responsibility: data quality only.  For each enriched SearchResult, Agent1
compares the same information across the three available sources
(BoondManager structured fields, CV extracted text, technical document) and
writes a normalised view into ``result.data`` under ``_normalized_*`` keys.

Agent0 uses those keys for matching; the raw BoondManager payload is
preserved unchanged so nothing downstream is broken by this pass.

Normalised keys written into ``result.data``:
  _normalized_experience_years   int | None   — best years estimate
  _normalized_experience_source  str | None   — which source won
  _normalized_skills             list[str]    — deduplicated union
  _normalized_languages          list[str]    — deduplicated union
  _normalized_title              str | None   — best title estimate

Design constraints for v1:
  - Pure Python heuristics, no LLM calls.
  - No new I/O; all data is already in ``result.data`` from enrichment.
  - Idempotent: running twice produces the same result.
  - Extensible: each dimension is a standalone function.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from app.models.results import SearchResult
from app.skill_patterns import KNOWN_SKILL_PATTERNS

logger = logging.getLogger(__name__)

# Keys used to store normalised data; prefixed with _normalized_ to stay
# clearly separate from BoondManager raw fields.
NORM_EXPERIENCE_YEARS: Final[str] = "_normalized_experience_years"
NORM_EXPERIENCE_SOURCE: Final[str] = "_normalized_experience_source"
NORM_SKILLS: Final[str] = "_normalized_skills"
NORM_LANGUAGES: Final[str] = "_normalized_languages"
NORM_TITLE: Final[str] = "_normalized_title"

# Enrichment payload keys (mirrors nodes.py constants).
_ENRICHMENT_TECH_DOC_KEY: Final[str] = "_enrichment_technical_document"
_ENRICHMENT_RESUME_KEY: Final[str] = "_enrichment_resume"
_ENRICHMENT_DETAIL_KEY: Final[str] = "_enrichment_detail"
_ENRICHMENT_ADMINISTRATIVE_KEY: Final[str] = "_enrichment_administrative"

# --- experience extraction ------------------------------------------------

# Year figures are only trusted when they are explicitly tied to *experience*,
# otherwise free-text mining grabs unrelated numbers ("4 years of data",
# "40 ans" referring to an age/date, company history, etc.). We require an
# experience keyword adjacent to the number, in either order.
_UNIT = r"(?:ans?|années?|years?)"
_EXP_KW = r"(?:expérience|experience|exp\b)"

_YEARS_RES: Final[tuple[re.Pattern[str], ...]] = (
    # "6 years of Experience", "3+ years of hands-on technical experience",
    # "10 ans d'expérience" — number → unit → (short gap) → experience keyword.
    # The gap excludes sentence/clause separators (. , ;) so the number and the
    # experience keyword must sit in the same clause — "40 ans. … expérience"
    # never links the age to the keyword.
    re.compile(
        rf"(\d{{1,2}})\s*\+?\s*{_UNIT}[\s\w'’\-/]{{0,40}}?{_EXP_KW}",
        re.IGNORECASE,
    ),
    # "expérience: 16 ans", "experience of 12 years", "expérience de 16 ans" —
    # keyword → short connector only (:, of, de, d', en) → number → unit.
    # The connector is deliberately tight so "experience and 30 years old"
    # does NOT link the age to the experience keyword.
    re.compile(
        rf"{_EXP_KW}\s*(?::|of|de|d['’]|en)?\s*(\d{{1,2}})\s*\+?\s*{_UNIT}",
        re.IGNORECASE,
    ),
)


def _parse_years_from_text(text: str) -> int | None:
    """Largest experience-qualified years figure in free text.

    Only counts numbers explicitly tied to an experience keyword, so stray
    mentions ("4 years of data", "40 ans" as an age) are ignored.
    """
    best: int | None = None
    for pattern in _YEARS_RES:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except (ValueError, TypeError):
                continue
            # Sanity cap: ignore implausible values (> 50 years).
            if 0 < value <= 50 and (best is None or value > best):
                best = value
    return best


def _years_from_boond(data: dict[str, object]) -> int | None:
    """Read experienceMinYears from BoondManager structured fields."""
    for source in (data, data.get("attributes"), data.get(_ENRICHMENT_TECH_DOC_KEY)):
        if not isinstance(source, dict):
            continue
        for key in ("experienceMinYears", "experience_min_years"):
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and 0 < value <= 50:
                return value
            if isinstance(value, str):
                try:
                    v = int(value.strip())
                    if 0 < v <= 50:
                        return v
                except ValueError:
                    pass
    return None


# Top-level text fields in result.data that may contain experience mentions.
_TOP_LEVEL_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "title", "headline", "snippet", "description", "summary",
    "resumeTd", "resume", "skills",
)
# Tech doc nested text fields.
_TECH_DOC_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "text", "description", "summary", "skills", "title",
)


def _normalize_experience(data: dict[str, object]) -> tuple[int | None, str | None]:
    """Return (best_years, source_label) reconciling structured + free-text data.

    Strategy:
      1. Trust BoondManager's structured ``experienceMinYears`` when present —
         it is curated and authoritative.
      2. Otherwise fall back to experience-qualified figures mined from free
         text (tech doc → CV → profile title/snippet), taking the highest
         plausible value. Free-text mining only counts numbers explicitly tied
         to an experience keyword, so stray "X years" mentions are ignored.
    """
    boond_years = _years_from_boond(data)
    if boond_years is not None:
        return boond_years, "boondmanager"

    # Tech doc free-text fields (summary may say "3+ years of hands-on experience")
    techdoc_years: int | None = None
    techdoc = data.get(_ENRICHMENT_TECH_DOC_KEY)
    if isinstance(techdoc, dict):
        td_text = " ".join(
            str(techdoc.get(f))
            for f in _TECH_DOC_TEXT_FIELDS
            if isinstance(techdoc.get(f), str) and techdoc.get(f)
        )
        techdoc_years = _parse_years_from_text(td_text) if td_text else None

    # CV extracted text
    cv_years: int | None = None
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        cv_text = resume.get("extractedText") or resume.get("text") or ""
        if isinstance(cv_text, str) and cv_text:
            cv_years = _parse_years_from_text(cv_text)

    # Top-level text (title like "Python Engineer 6 years of Experience", snippet)
    top_text = " ".join(
        str(data.get(f))
        for f in _TOP_LEVEL_TEXT_FIELDS
        if isinstance(data.get(f), str) and data.get(f)
    )
    top_years = _parse_years_from_text(top_text) if top_text else None

    # Free-text fallback, in order of reliability; take the highest qualified hit.
    for years, source in (
        (techdoc_years, "technical_document"),
        (cv_years, "cv"),
        (top_years, "profile_text"),
    ):
        if years is not None:
            return years, source

    return None, None


# --- skills extraction ----------------------------------------------------

# Delimiters used by BoondManager's free-text "skills" field.
_SKILL_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[,;/\n\r]+")
# Max length of a single skill token; longer = a sentence, not a skill.
_MAX_SKILL_TOKEN_LEN: Final[int] = 40


def _add_skill_token(token: str, sink: list[str]) -> None:
    """Append a cleaned skill token, dropping blobs and overlong sentences."""
    cleaned = token.strip()
    if cleaned and len(cleaned) <= _MAX_SKILL_TOKEN_LEN:
        sink.append(cleaned)


def _collect_boond_skills(data: dict[str, object]) -> list[str]:
    """Extract skills from BoondManager structured fields (detail + tech-doc).

    The ``skills`` field is often a single comma/newline-separated string
    (e.g. "python, java, scala, sql") — split it so each becomes its own
    tag rather than one giant blob.
    """
    skills: list[str] = []
    for source in (data, data.get("attributes"), data.get(_ENRICHMENT_TECH_DOC_KEY), data.get(_ENRICHMENT_DETAIL_KEY)):
        if not isinstance(source, dict):
            continue
        for field in ("skills", "tools", "expertiseAreas"):
            value = source.get(field)
            if isinstance(value, str) and value.strip():
                for part in _SKILL_SPLIT_RE.split(value):
                    _add_skill_token(part, skills)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        _add_skill_token(item, skills)
                    elif isinstance(item, dict):
                        label = (
                            item.get("tool")
                            or item.get("label")
                            or item.get("name")
                            or item.get("title")
                        )
                        if isinstance(label, str) and label.strip():
                            _add_skill_token(label, skills)
    return skills


# Common tech skill patterns: recognise capitalised/upper-case tokens and
# known compound phrases.  Kept minimal for v1; Agent1 can be extended with
# an LLM call later without changing the interface.
_TECH_SKILL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([A-Z][a-zA-Z0-9+#.\-]{1,30}|[A-Z]{2,10})\b"
)

# Stopwords that look like skills but are not.
_SKILL_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "Je", "En", "Le", "La", "Les", "De", "Du", "Des", "Un", "Une",
        "Et", "Ou", "Par", "Sur", "Dans", "Pour", "Avec", "Sans",
        "Je", "Tu", "Il", "Nous", "Vous", "Ils",
        "The", "And", "For", "With", "From", "Not", "Are", "Was",
        "Has", "Have", "Had", "This", "That", "Will", "Been",
        "CV", "CDD", "CDI", "Mr", "Mme", "Dr", "PhD",
    }
)


def _extract_skills_from_text(text: str, boond_skills: set[str]) -> list[str]:
    """Heuristic extraction of tech skills from free text not already in boond_skills.

    Only runs when BoondManager structured skills are sparse (< 3 entries)
    so we don't noisily override rich structured data with text-mining.
    """
    if len(boond_skills) >= 3:
        return []
    found: list[str] = []
    seen: set[str] = set(s.lower() for s in boond_skills)
    for match in _TECH_SKILL_RE.finditer(text):
        token = match.group(1)
        if token in _SKILL_STOPWORDS:
            continue
        if token.lower() not in seen:
            found.append(token)
            seen.add(token.lower())
    return found


def _pattern_skills_from_text(text: str, seen: set[str]) -> list[str]:
    """Extract known tech skills from free text using the shared pattern list.

    Uses the same patterns as candidate_mapper so the skill labels are
    identical and the frontend deduplicates them correctly.
    """
    found: list[str] = []
    for pattern, label in KNOWN_SKILL_PATTERNS:
        if label.lower() not in seen and re.search(pattern, text, re.IGNORECASE):
            found.append(label)
            seen.add(label.lower())
    return found


def _normalize_skills(data: dict[str, object]) -> list[str]:
    """Union of skills from all sources, deduplicated (case-insensitive).

    Priority:
    1. BoondManager structured fields (most reliable, already curated)
    2. Tech doc free-text fields (summary, description, text) — catches
       skills mentioned in prose but not added to the structured list
    3. CV extracted text — widest coverage but noisiest
    """
    result: list[str] = []
    seen: set[str] = set()

    # 1. Structured fields from BoondManager / tech doc / detail
    for skill in _collect_boond_skills(data):
        if skill.lower() not in seen:
            result.append(skill)
            seen.add(skill.lower())

    # 2. Tech doc free-text (summary, description, text)
    techdoc = data.get(_ENRICHMENT_TECH_DOC_KEY)
    if isinstance(techdoc, dict):
        for field in ("summary", "description", "text", "skills"):
            value = techdoc.get(field)
            if isinstance(value, str) and value.strip():
                for skill in _pattern_skills_from_text(value, seen):
                    result.append(skill)

    # 3. CV extracted text — only when structured + tech doc are sparse
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        cv_text = str(resume.get("extractedText") or resume.get("text") or "")
        if cv_text:
            # Pattern-based extraction first (reliable labels)
            for skill in _pattern_skills_from_text(cv_text, seen):
                result.append(skill)
            # Heuristic fallback only when still very sparse
            if len(result) < 3:
                for skill in _extract_skills_from_text(cv_text, seen):
                    result.append(skill)

    return result


# --- language extraction --------------------------------------------------

_LANGUAGE_KEYWORDS: Final[dict[str, str]] = {
    "anglais": "Anglais",
    "english": "Anglais",
    "français": "Français",
    "french": "Français",
    "francais": "Français",
    "allemand": "Allemand",
    "german": "Allemand",
    "espagnol": "Espagnol",
    "spanish": "Espagnol",
    "italien": "Italien",
    "italian": "Italien",
    "portugais": "Portugais",
    "portuguese": "Portugais",
    "arabe": "Arabe",
    "arabic": "Arabe",
    "chinois": "Chinois",
    "chinese": "Chinois",
    "japonais": "Japonais",
    "japanese": "Japonais",
    "russe": "Russe",
    "russian": "Russe",
    "néerlandais": "Néerlandais",
    "dutch": "Néerlandais",
}

_LEVEL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(A1|A2|B1|B2|C1|C2|natif|native|courant|fluent|professionnel|professional|bilingue|bilingual|notions?|basic|débutant)\b",
    re.IGNORECASE,
)


def _collect_boond_languages(data: dict[str, object]) -> list[str]:
    """Extract language labels from BoondManager structured fields."""
    langs: list[str] = []
    for source in (data, data.get("attributes"), data.get(_ENRICHMENT_TECH_DOC_KEY), data.get(_ENRICHMENT_DETAIL_KEY)):
        if not isinstance(source, dict):
            continue
        value = source.get("languages")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    langs.append(item.strip())
                elif isinstance(item, dict):
                    label = (
                        item.get("_languageSpokenLabel")
                        or item.get("label")
                        or item.get("name")
                    )
                    level = item.get("_languageLevelLabel") or item.get("level")
                    if isinstance(label, str) and label.strip():
                        entry = label.strip()
                        if isinstance(level, str) and level.strip():
                            entry = f"{entry} ({level.strip()})"
                        langs.append(entry)
    return langs


def _extract_languages_from_text(text: str, existing: set[str]) -> list[str]:
    """Detect language mentions in CV text not already in existing."""
    text_lower = text.lower()
    found: list[str] = []
    for keyword, canonical in _LANGUAGE_KEYWORDS.items():
        if keyword in text_lower and canonical.lower() not in existing:
            # Try to pick up an adjacent level qualifier.
            pattern = re.compile(
                rf"\b{re.escape(keyword)}\b[^.;\n]{{0,40}}",
                re.IGNORECASE,
            )
            match = pattern.search(text_lower)
            level_match = _LEVEL_RE.search(match.group(0)) if match else None
            entry = canonical
            if level_match:
                entry = f"{canonical} ({level_match.group(0).strip()})"
            found.append(entry)
            existing.add(canonical.lower())
    return found


def _normalize_languages(data: dict[str, object]) -> list[str]:
    """Union of languages from all sources, deduplicated."""
    boond = _collect_boond_languages(data)
    result: list[str] = []
    seen: set[str] = set()
    for lang in boond:
        # Normalise to the canonical name for dedup.
        canonical = _LANGUAGE_KEYWORDS.get(lang.split("(")[0].strip().lower())
        key = (canonical or lang).lower()
        if key not in seen:
            result.append(lang)
            seen.add(key)

    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        text = str(resume.get("extractedText") or resume.get("text") or "")
        if text:
            extra = _extract_languages_from_text(text, seen)
            result.extend(extra)

    return result


# --- title normalisation --------------------------------------------------

def _normalize_title(data: dict[str, object], current_title: str | None) -> str | None:
    """Return the best title estimate.

    Prefers the BoondManager title when non-empty; otherwise tries to pull a
    job title from the detail/tech-doc payload.
    """
    if current_title and current_title.strip():
        return current_title.strip()
    for source in (data.get(_ENRICHMENT_TECH_DOC_KEY), data.get(_ENRICHMENT_DETAIL_KEY)):
        if not isinstance(source, dict):
            continue
        for field in ("title", "jobTitle", "headline", "position"):
            value = source.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return current_title


# --- public API -----------------------------------------------------------

def normalize_candidate(result: SearchResult) -> SearchResult:
    """Produce a normalised copy of *result* with ``_normalized_*`` keys set.

    Pure function: reads ``result.data``, returns a new ``SearchResult``
    with an updated ``data`` dict. The original payload is untouched.
    """
    data = dict(result.data)

    # Expose SearchResult scalar fields into data so _normalize_* functions
    # have a single dict to scan without needing access to the full result.
    if result.title and "title" not in data:
        data["title"] = result.title
    if result.snippet and "snippet" not in data:
        data["snippet"] = result.snippet

    exp_years, exp_source = _normalize_experience(data)
    skills = _normalize_skills(data)
    languages = _normalize_languages(data)
    title = _normalize_title(data, result.title)

    data[NORM_EXPERIENCE_YEARS] = exp_years
    data[NORM_EXPERIENCE_SOURCE] = exp_source
    data[NORM_SKILLS] = skills
    data[NORM_LANGUAGES] = languages
    data[NORM_TITLE] = title

    logger.debug(
        "agent1.normalize_candidate",
        extra={
            "candidate_id": result.id,
            "exp_years": exp_years,
            "exp_source": exp_source,
            "skills_count": len(skills),
            "languages_count": len(languages),
        },
    )

    return result.model_copy(update={"data": data})


def normalize_candidates(results: list[SearchResult]) -> list[SearchResult]:
    """Normalise all results in *results*, returning a new list.

    Non-search results (e.g. detail-by-id lookups) are normalised too —
    the normaliser is idempotent and harmless on sparse data.
    """
    return [normalize_candidate(r) for r in results]
