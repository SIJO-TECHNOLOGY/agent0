"""Build the text that represents a candidate in the vector index.

The embedded document is deliberately assembled from the *skill-bearing*
surfaces only — title, skills, expertise, technical document, CV text —
mirroring ``nodes._evidence_haystack``. Administrative noise (emails,
ids, addresses, salary) is excluded: it adds no semantic signal and
would dilute the embedding.

The document is capped so one candidate always fits a single embedding
call; the CV text is truncated last because it is both the longest and
the most redundant surface.
"""

from __future__ import annotations

import re
from typing import Final

# Fields carrying skill signal on a searchCandidates summary / detail.
_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "skills",
    "expertiseAreas",
    "activityAreas",
    "tools",
    "diplomas",
    "languages",
)
_TECH_DOC_FIELDS: Final[tuple[str, ...]] = (
    "skills",
    "expertiseAreas",
    "activityAreas",
    "tools",
    "languages",
    "content",
    "text",
)

# ~8k chars keeps us far inside text-embedding-3-small's 8192-token window
# even for token-dense French CVs.
MAX_DOC_CHARS: Final[int] = 7500
_MAX_CV_CHARS: Final[int] = 6000


def _collect(value: object, into: list[str]) -> None:
    """Flatten strings out of scalars / lists / dicts into ``into``."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            into.append(text)
    elif isinstance(value, (int, float)):
        into.append(str(value))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect(item, into)
    elif isinstance(value, dict):
        for item in value.values():
            _collect(item, into)


def _clean(text: str) -> str:
    """Collapse whitespace; keep original casing for the embedding model."""
    return re.sub(r"\s+", " ", text).strip()


def build_candidate_document(
    *,
    summary: dict[str, object] | None = None,
    technical_document: dict[str, object] | None = None,
    cv: dict[str, object] | None = None,
) -> str:
    """Assemble the embeddable document for one candidate.

    Returns ``""`` when no skill-bearing content exists, which the caller
    must treat as "not indexable" rather than embedding an empty string.
    """
    parts: list[str] = []

    if summary:
        for field in _SUMMARY_FIELDS:
            _collect(summary.get(field), parts)
        # experienceLabelRaw ("10 ans") carries seniority phrasing that the
        # embedding can relate to "senior" / "confirme" in a query.
        _collect(summary.get("experienceLabelRaw"), parts)

    if technical_document:
        for field in _TECH_DOC_FIELDS:
            _collect(technical_document.get(field), parts)

    cv_text = ""
    if cv and cv.get("hasContent"):
        raw: list[str] = []
        for field in ("text", "content", "extractedText"):
            _collect(cv.get(field), raw)
        cv_text = _clean(" ".join(raw))[:_MAX_CV_CHARS]

    head = _clean(" ".join(parts))
    if not head and not cv_text:
        return ""

    document = f"{head} {cv_text}".strip() if cv_text else head
    return document[:MAX_DOC_CHARS]


def build_query_document(
    *,
    entities: list[str] | None = None,
    objective: str = "",
    role: str | None = None,
) -> str:
    """Assemble the query side of the comparison from the interpreted intent.

    Kept symmetric with the candidate document: a bag of skill/role terms
    plus the free-text objective, so both sides live in the same region of
    the embedding space.
    """
    parts: list[str] = []
    if role:
        parts.append(role)
    for entity in entities or []:
        _collect(entity, parts)
    if objective:
        parts.append(objective)
    return _clean(" ".join(parts))[:MAX_DOC_CHARS]
