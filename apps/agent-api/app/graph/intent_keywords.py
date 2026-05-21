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

_SENIORITY_TERMS: Final[dict[str, str]] = {
    "junior": "junior",
    "intermediate": "intermediate",
    "mid": "intermediate",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
}

_TYPE_HINTS: Final[dict[str, str]] = {
    "consultant": "search_consultants",
    "consultants": "search_consultants",
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
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "find",
        "search",
        "show",
        "me",
        "list",
        "in",
        "on",
        "available",
        "who",
        "are",
        "is",
        "to",
        "next",
        "this",
        "that",
        "any",
        "all",
        "by",
    }
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
