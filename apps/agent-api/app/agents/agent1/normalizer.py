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

_YEARS_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+)\s*(?:ans?|années?|year[s]?\s*(?:of\s*experience)?)",
    re.IGNORECASE,
)
# Seniority title keywords → approximate minimum years.
_TITLE_SENIORITY: Final[dict[str, int]] = {
    "junior": 1,
    "mid": 3,
    "confirmed": 3,
    "confirmé": 3,
    "senior": 5,
    "lead": 7,
    "principal": 8,
    "architect": 8,
    "architecte": 8,
    "expert": 8,
    "staff": 8,
}


def _parse_years_from_text(text: str) -> int | None:
    """Largest explicit years-of-experience figure in free text."""
    best: int | None = None
    for match in _YEARS_RE.finditer(text):
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


def _normalize_experience(data: dict[str, object]) -> tuple[int | None, str | None]:
    """Return (best_years, source_label) by reconciling all sources.

    Strategy: prefer the highest plausible figure across sources, because
    BoondManager often stores the minimum experience band while the CV or
    technical document mentions the actual years worked.
    """
    boond_years = _years_from_boond(data)

    cv_years: int | None = None
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        text = resume.get("extractedText") or resume.get("text") or ""
        if isinstance(text, str) and text:
            cv_years = _parse_years_from_text(text)

    techdoc_years: int | None = None
    techdoc = data.get(_ENRICHMENT_TECH_DOC_KEY)
    if isinstance(techdoc, dict):
        text = str(techdoc.get("text") or techdoc.get("description") or "")
        techdoc_years = _parse_years_from_text(text)

    candidates = [
        (boond_years, "boondmanager"),
        (cv_years, "cv"),
        (techdoc_years, "technical_document"),
    ]
    best_years: int | None = None
    best_source: str | None = None
    for years, source in candidates:
        if years is not None and (best_years is None or years > best_years):
            best_years = years
            best_source = source

    return best_years, best_source


# --- skills extraction ----------------------------------------------------

def _collect_boond_skills(data: dict[str, object]) -> list[str]:
    """Extract skills from BoondManager structured fields (detail + tech-doc)."""
    skills: list[str] = []
    for source in (data, data.get("attributes"), data.get(_ENRICHMENT_TECH_DOC_KEY), data.get(_ENRICHMENT_DETAIL_KEY)):
        if not isinstance(source, dict):
            continue
        for field in ("skills", "tools", "expertiseAreas"):
            value = source.get(field)
            if isinstance(value, str) and value.strip():
                skills.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        skills.append(item.strip())
                    elif isinstance(item, dict):
                        label = item.get("label") or item.get("name") or item.get("title")
                        if isinstance(label, str) and label.strip():
                            skills.append(label.strip())
    return skills


# Minimum length for a skill token extracted from free text.
_MIN_SKILL_LEN: Final[int] = 2

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


def _normalize_skills(data: dict[str, object]) -> list[str]:
    """Union of skills from all sources, deduplicated (case-insensitive)."""
    boond = _collect_boond_skills(data)
    result: list[str] = []
    seen: set[str] = set()
    for skill in boond:
        if skill.lower() not in seen:
            result.append(skill)
            seen.add(skill.lower())

    # Supplement from CV when structured data is sparse.
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        text = str(resume.get("extractedText") or resume.get("text") or "")
        if text:
            extra = _extract_skills_from_text(text, seen)
            result.extend(extra[:20])  # cap to avoid noise

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
