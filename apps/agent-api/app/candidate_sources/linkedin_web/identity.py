"""Identity matching between a known candidate and a public LinkedIn profile.

Used by the "find the public profile for this Boond candidate" capability and
by cross-source deduplication. Confidence is graded so the caller can apply
the SIJO rule: only ``strong`` matches are ever auto-merged as the same
physical person; ``probable`` / ``ambiguous`` are surfaced but never merged
(and a name-only match is never ``strong``).

Pure functions only.
"""

from __future__ import annotations

import re
import unicodedata

from app.candidate_sources.models import ExternalProfileMatch

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokens(text: str | None) -> set[str]:
    return {t for t in _TOKEN_RE.findall(_fold(text)) if len(t) > 1}


def _name_recall(requested: str | None, candidate: str | None) -> float:
    req = _tokens(requested)
    if not req:
        return 0.0
    cand = _tokens(candidate)
    if not cand:
        return 0.0
    return sum(1 for tok in req if tok in cand) / len(req)


def _overlaps(a: str | None, b: str | None) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb and (ta & tb))


def score_profile_match(
    *,
    known_name: str | None,
    known_company: str | None = None,
    known_previous_company: str | None = None,
    known_title: str | None = None,
    known_location: str | None = None,
    profile_url: str | None,
    profile_name: str | None,
    profile_company: str | None = None,
    profile_title: str | None = None,
    profile_location: str | None = None,
) -> ExternalProfileMatch:
    """Grade how confidently a profile is the same person as the known one.

    A full name match is necessary but never sufficient for ``strong`` — at
    least one corroborating dimension (company / title / location) must also
    match. This encodes "do not automatically merge on name alone".
    """
    name_recall = _name_recall(known_name, profile_name)
    matched_name = name_recall >= 1.0
    matched_company = _overlaps(known_company, profile_company) or _overlaps(
        known_previous_company, profile_company
    )
    matched_title = _overlaps(known_title, profile_title)
    matched_location = _overlaps(known_location, profile_location)

    corroborations = sum(
        (matched_company, matched_title, matched_location)
    )

    score = (
        0.55 * name_recall
        + 0.25 * (1.0 if matched_company else 0.0)
        + 0.12 * (1.0 if matched_title else 0.0)
        + 0.08 * (1.0 if matched_location else 0.0)
    )

    if matched_name and corroborations >= 2:
        level = "strong"
    elif matched_name and corroborations == 1:
        level = "probable"
    else:
        # Name-only (even exact) or partial name → never strong.
        level = "ambiguous"

    return ExternalProfileMatch(
        confidence_level=level,
        score=round(score, 4),
        profile_url=profile_url,
        matched_name=matched_name,
        matched_company=matched_company,
        matched_title=matched_title,
        matched_location=matched_location,
    )
