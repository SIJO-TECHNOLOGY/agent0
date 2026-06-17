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
# Conflict reasons detected by the deterministic pass; non-empty means the
# candidate's data is ambiguous and is a candidate for LLM reconciliation.
NORM_CONFLICTS: Final[str] = "_normalized_conflicts"

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

# Gap allowed between the number+unit and the experience keyword. Letters,
# spaces, apostrophes, hyphens and slashes only — crucially NO digits, so a
# nearby age ("40 ans") can never jump over an intervening figure ("16 ans
# d'expérience") to reach the keyword. Sentence separators (. , ;) are also
# excluded, keeping the number and keyword in the same clause.
_EXP_GAP = r"[\sA-Za-zÀ-ÿ'’\-/]{0,40}?"

# High-precision pattern: keyword → MANDATORY connector (:, of, de, d', en) →
# number → unit. e.g. "Expérience: 16 ans", "experience of 10 years". The
# connector requirement means a labelled field like "Expérience: 16 ans" is
# read unambiguously, and "d'expérience 40 ans" (age after the keyword, no
# connector) is NOT captured.
_YEARS_RE_KEYWORD_FIRST: Final[re.Pattern[str]] = re.compile(
    rf"{_EXP_KW}\s*(?::|of|de|d['’]|en)\s*(\d{{1,2}})\s*\+?\s*{_UNIT}",
    re.IGNORECASE,
)

# Fallback pattern: number → unit → (digit-free gap) → keyword. e.g.
# "16 ans d'expérience", "3+ years of hands-on technical experience". The
# digit-free gap stops a nearby age ("40 ans") from jumping over an
# intervening figure to reach the keyword.
_YEARS_RE_NUMBER_FIRST: Final[re.Pattern[str]] = re.compile(
    rf"(\d{{1,2}})\s*\+?\s*{_UNIT}{_EXP_GAP}{_EXP_KW}",
    re.IGNORECASE,
)


def _largest_match(pattern: re.Pattern[str], text: str) -> int | None:
    best: int | None = None
    for match in pattern.finditer(text):
        try:
            value = int(match.group(1))
        except (ValueError, TypeError):
            continue
        # Sanity cap: ignore implausible values (> 50 years).
        if 0 < value <= 50 and (best is None or value > best):
            best = value
    return best


def _parse_years_from_text(text: str) -> int | None:
    """Experience-qualified years figure in free text.

    Only counts numbers explicitly tied to an experience keyword, so stray
    mentions ("4 years of data", "40 ans" as an age) are ignored.

    The high-precision "keyword: number" form is tried first; only if it finds
    nothing do we fall back to the looser "number ... keyword" form. This avoids
    a labelled age ("40 ans   Expérience: 16 ans") being misread as 40.
    """
    keyword_first = _largest_match(_YEARS_RE_KEYWORD_FIRST, text)
    if keyword_first is not None:
        return keyword_first
    return _largest_match(_YEARS_RE_NUMBER_FIRST, text)


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

    Strategy (policy: trust the CV when it *clearly* states experience):
      1. If the CV explicitly states a years-of-experience figure (a number
         tied to an experience keyword, e.g. "3+ years of hands-on technical
         experience", "16 ans d'expérience"), use it — the candidate's own
         clear statement wins over the structured field, which is often a
         coarse band or stale.
      2. Else trust BoondManager's structured ``experienceMinYears``.
      3. Else, if a structured experience *level* is present
         (``_experienceLabel``, e.g. "10 à 15 ans") but no exact figure, show
         that band label instead of guessing a number (numeric years stay None).
      4. Else fall back to experience-qualified figures from the technical
         document, then the profile title/snippet.

    Free-text mining only counts a number explicitly tied to an experience
    keyword in the same clause, so an age ("40 ans"), a duration ("4 years of
    data"), or company history never inflates the value.
    """
    # 1. CV — the candidate's own clearly-stated experience takes priority.
    cv_years: int | None = None
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        cv_text = resume.get("extractedText") or resume.get("text") or ""
        if isinstance(cv_text, str) and cv_text:
            cv_years = _parse_years_from_text(cv_text)
    if cv_years is not None:
        return cv_years, "cv"

    # 2. Structured BoondManager min-years.
    boond_years = _years_from_boond(data)
    if boond_years is not None:
        return boond_years, "boondmanager"

    # 3. Structured experience level (band) — show the label, don't guess a number.
    exp_label = data.get("_experienceLabel")
    if isinstance(exp_label, str) and exp_label.strip():
        return None, None

    # 4. Technical document, then profile title/snippet.
    techdoc = data.get(_ENRICHMENT_TECH_DOC_KEY)
    if isinstance(techdoc, dict):
        td_text = " ".join(
            str(techdoc.get(f))
            for f in _TECH_DOC_TEXT_FIELDS
            if isinstance(techdoc.get(f), str) and techdoc.get(f)
        )
        td_years = _parse_years_from_text(td_text) if td_text else None
        if td_years is not None:
            return td_years, "technical_document"

    top_text = " ".join(
        str(data.get(f))
        for f in _TOP_LEVEL_TEXT_FIELDS
        if isinstance(data.get(f), str) and data.get(f)
    )
    top_years = _parse_years_from_text(top_text) if top_text else None
    if top_years is not None:
        return top_years, "profile_text"

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


# --- conflict detection ---------------------------------------------------

# An age mention: "40 ans", "âgé de 40 ans", "40 years old", "aged 40".
_AGE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{2})\s*(?:ans?\b(?!\s*(?:d['’\s]*|de\s+)?exp)|years?\s*old\b)"
    r"|âgé[e]?\s*(?:de\s*)?(\d{2})\s*ans?"
    r"|aged\s*(\d{2})\b",
    re.IGNORECASE,
)
# Seniority keywords in a title, mapped to a rough minimum years expectation.
_TITLE_SENIORITY_MIN: Final[dict[str, int]] = {
    "junior": 0, "débutant": 0, "stagiaire": 0,
    "senior": 5, "confirmé": 3, "lead": 7, "principal": 8,
    "architecte": 8, "architect": 8, "expert": 8, "staff": 8,
}


def _experience_text(data: dict[str, object]) -> str:
    """Combined free text used for experience conflict checks (CV + tech doc + title)."""
    parts: list[str] = []
    resume = data.get(_ENRICHMENT_RESUME_KEY)
    if isinstance(resume, dict):
        parts.append(str(resume.get("extractedText") or resume.get("text") or ""))
    techdoc = data.get(_ENRICHMENT_TECH_DOC_KEY)
    if isinstance(techdoc, dict):
        parts.extend(
            str(techdoc.get(f)) for f in _TECH_DOC_TEXT_FIELDS
            if isinstance(techdoc.get(f), str)
        )
    for f in ("title", "headline", "snippet", "description", "summary"):
        if isinstance(data.get(f), str):
            parts.append(str(data.get(f)))
    return " ".join(p for p in parts if p)


def _all_qualified_years(text: str) -> set[int]:
    """All distinct experience-qualified year figures in the text."""
    found: set[int] = set()
    for pattern in (_YEARS_RE_KEYWORD_FIRST, _YEARS_RE_NUMBER_FIRST):
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except (ValueError, TypeError):
                continue
            if 0 < value <= 50:
                found.add(value)
    return found


def detect_conflicts(
    data: dict[str, object],
    *,
    exp_years: int | None,
    exp_source: str | None,
) -> list[str]:
    """Return a list of data-coherence conflict reasons (empty = coherent).

    A non-empty result marks the candidate as ambiguous — a good target for
    LLM reconciliation. Heuristic and conservative: it flags *suspicion*, the
    LLM does the actual judging.
    """
    reasons: list[str] = []
    text = _experience_text(data)

    # 1. Several different experience figures stated in the text.
    qualified = _all_qualified_years(text)
    if len(qualified) >= 2:
        reasons.append("experience_multiple_figures")

    # 2. An age mention coexists with an experience figure (the 40-vs-16 trap).
    if exp_years is not None and _AGE_RE.search(text):
        reasons.append("age_present_with_experience")

    # 3. Free-text experience disagrees with the structured BoondManager value.
    boond_years = _years_from_boond(data)
    if (
        exp_years is not None
        and boond_years is not None
        and exp_source != "boondmanager"
        and abs(exp_years - boond_years) >= 3
    ):
        reasons.append("experience_vs_structured_disagreement")

    # 4. Title seniority keyword inconsistent with the resolved years.
    title = data.get(NORM_TITLE) or data.get("title")
    if isinstance(title, str) and exp_years is not None:
        low = title.lower()
        for kw, min_years in _TITLE_SENIORITY_MIN.items():
            if kw in low:
                if kw in ("junior", "débutant", "stagiaire") and exp_years >= 7:
                    reasons.append("title_seniority_mismatch")
                elif min_years >= 5 and exp_years < 2:
                    reasons.append("title_seniority_mismatch")
                break

    return reasons


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

    conflicts = detect_conflicts(data, exp_years=exp_years, exp_source=exp_source)
    data[NORM_CONFLICTS] = conflicts

    logger.debug(
        "agent1.normalize_candidate",
        extra={
            "candidate_id": result.id,
            "exp_years": exp_years,
            "exp_source": exp_source,
            "skills_count": len(skills),
            "languages_count": len(languages),
            "conflicts": conflicts,
        },
    )

    return result.model_copy(update={"data": data})


def normalize_candidates(results: list[SearchResult]) -> list[SearchResult]:
    """Normalise all results in *results*, returning a new list.

    Non-search results (e.g. detail-by-id lookups) are normalised too —
    the normaliser is idempotent and harmless on sparse data.
    """
    return [normalize_candidate(r) for r in results]
