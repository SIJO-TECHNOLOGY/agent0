"""Deterministic keyword heuristics used by the MVP planner.

The MVP avoids LLM calls and uses simple keyword detection so the
workflow remains deterministic and testable. Real LLM-backed
analysis can replace these heuristics later behind the same node
interface.
"""

from __future__ import annotations

import re
from typing import Final

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")

# Matches phrases like "candidate id 41924", "candidateId=41924", "candidate#41924",
# and the common typo "cadidate id 41924". Requires an "id"-style anchor so we
# don't over-trigger on stray numbers.
_CANDIDATE_ID_RE: re.Pattern[str] = re.compile(
    r"\b(?:candidate|cadidate)\s*(?:id|ids|_id|#)\s*[:=]?\s*(\d+)\b",
    re.IGNORECASE,
)

_SENIORITY_TERMS: Final[dict[str, str]] = {
    "junior": "junior",
    "intermediate": "intermediate",
    "mid": "intermediate",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
}

_TYPE_HINTS: Final[dict[str, str]] = {
    "candidate": "search_consultants",
    "candidates": "search_consultants",
    "consultant": "search_consultants",
    "consultants": "search_consultants",
    "dev": "search_consultants",
    "devs": "search_consultants",
    "developer": "search_consultants",
    "developers": "search_consultants",
    "engineer": "search_consultants",
    "engineers": "search_consultants",
    "profile": "search_consultants",
    "profiles": "search_consultants",
    "project": "search_projects",
    "projects": "search_projects",
    "mission": "search_projects",
    "missions": "search_projects",
    "opportunity": "search_opportunities",
    "opportunities": "search_opportunities",
    "deal": "search_opportunities",
    "deals": "search_opportunities",
}

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # Articles and conjunctions
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "from",
        # Verbs/imperatives that frame the request
        "find",
        "search",
        "show",
        "list",
        "get",
        "fetch",
        "give",
        # Pronouns / determiners
        "me",
        "my",
        "i",
        "his",
        "her",
        "their",
        "they",
        "we",
        "us",
        "you",
        "your",
        "him",
        # Auxiliaries / modals
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "should",
        "would",
        "could",
        "can",
        "must",
        "may",
        "might",
        "will",
        "shall",
        # Question / connector words
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        # Common adverbs / prepositions
        "in",
        "on",
        "to",
        "at",
        "by",
        "as",
        "than",
        "then",
        # Quantifiers that don't help keyword filtering
        "any",
        "all",
        "more",
        "less",
        "most",
        "few",
        "many",
        "much",
        # Search-specific noise
        "available",
        "next",
        "this",
        "that",
        "year",
        "years",
        "yrs",
        "month",
        "months",
        "experience",
        "experiences",
        "last",
        "first",
        "previous",
        "current",
        "about",
        "around",
        "looking",
        "need",
        "want",
        "wanted",
        "wanting",
    }
)


_YEARS_EXPERIENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:year|yr)s?\b",
    re.IGNORECASE,
)


def tokenize(query: str) -> list[str]:
    """Return lowercase tokens from a query."""
    return [match.group(0).lower() for match in WORD_RE.finditer(query)]


def extract_keywords(query: str) -> list[str]:
    """Return de-duplicated content keywords useful as tool inputs."""
    tokens = tokenize(query)
    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _STOPWORDS or token in _SENIORITY_TERMS:
            continue
        if token in _TYPE_HINTS:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords


def extract_seniority(query: str) -> str | None:
    """Return a normalized seniority label if present in the query."""
    for token in tokenize(query):
        normalized = _SENIORITY_TERMS.get(token)
        if normalized:
            return normalized
    return None


def extract_min_years_experience(query: str) -> int | None:
    """Return the smallest integer ``N`` mentioned as "<N> years" of experience.

    Accepts forms like "10 years experience", "more than 10 years", "10+ yrs".
    Returns ``None`` when no number is present so callers don't invent a
    filter the MCP server can't satisfy reliably.
    """
    matches = _YEARS_EXPERIENCE_RE.findall(query)
    if not matches:
        return None
    try:
        values = [int(value) for value in matches]
    except (TypeError, ValueError):
        return None
    return min(values) if values else None


def extract_candidate_id(query: str) -> int | None:
    """Return a candidate ID parsed from the query, or None.

    Accepts forms such as "candidate id 41924", "candidateId=41924",
    and the typo "cadidate id 41924". Requires an "id"-style anchor
    to avoid matching unrelated numbers in the query.
    """
    match = _CANDIDATE_ID_RE.search(query)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def detect_tools(query: str) -> list[str]:
    """Detect requested MCP tools from type hints in the query."""
    tools: list[str] = []
    seen: set[str] = set()
    for token in tokenize(query):
        tool = _TYPE_HINTS.get(token)
        if tool and tool not in seen:
            seen.add(tool)
            tools.append(tool)
    return tools
