"""Scoring for external (LinkedIn) candidates with tri-state semantics.

External public data is sparse: a criterion we cannot see is UNKNOWN, which is
NEUTRAL — it must never be scored like a confirmed NO. The score starts from a
neutral prior and is nudged up by positive evidence (matched skills, confirmed
consulting, confirmed long mission, seniority/location fit) and down only by
confirmed-negative evidence.

SIJO ranking priorities (section 20): technical fit, consulting evidence, and
long-mission evidence are the high-weight dimensions; seniority and location
are medium.

Pure functions — no I/O.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from app.candidate_sources.models import (
    CandidateSearchQuery,
    ExternalCandidateEvidence,
)

# Neutral prior for a discovered, on-target profile before evidence nudges.
_BASE: Final[float] = 0.5

# Positive weights.
_W_SKILLS: Final[float] = 0.20
_W_OPTIONAL_SKILLS: Final[float] = 0.05
_W_CONSULTING_CONFIRMED: Final[float] = 0.15
_W_CONSULTING_PROBABLE: Final[float] = 0.08
_W_MISSION_CONFIRMED: Final[float] = 0.20
_W_MISSION_PROBABLE: Final[float] = 0.10
_W_SENIORITY: Final[float] = 0.05
_W_LOCATION: Final[float] = 0.05
_W_ROLE: Final[float] = 0.05

# Negative weights — applied only for CONFIRMED-negative ("no") evidence.
_P_CONSULTING_NO: Final[float] = 0.10
_P_MISSION_NO: Final[float] = 0.12
_P_LOCATION_MISMATCH: Final[float] = 0.03


def _fold(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _matched(required: list[str], available: list[str]) -> int:
    avail = " ".join(_fold(a) for a in available)
    return sum(1 for skill in required if skill and _fold(skill) in avail)


def _total_experience_years(evidence: ExternalCandidateEvidence) -> int | None:
    months = [
        e.duration_months
        for e in evidence.experiences
        if isinstance(e.duration_months, int) and e.duration_months >= 0
    ]
    if not months:
        return None
    return sum(months) // 12


def score_external_candidate(
    evidence: ExternalCandidateEvidence,
    query: CandidateSearchQuery,
) -> tuple[float, dict[str, object]]:
    """Return ``(score in [0,1], breakdown)`` for one external candidate."""
    score = _BASE
    breakdown: dict[str, object] = {}

    # 1 — technical/functional fit (high). Matched skills add; UNMATCHED skills
    # are UNKNOWN (the public snippet may simply not list them) → no penalty.
    required = [s for s in query.required_skills if s and s.strip()]
    if required:
        matched = _matched(required, evidence.matched_skills)
        frac = matched / len(required)
        score += _W_SKILLS * frac
        breakdown["skills"] = f"{matched}/{len(required)} required skills visible"
    optional = [s for s in query.optional_skills if s and s.strip()]
    if optional:
        matched_opt = _matched(optional, evidence.matched_skills)
        if matched_opt:
            score += _W_OPTIONAL_SKILLS * (matched_opt / len(optional))

    # 2 — consulting evidence (high).
    consulting = evidence.consulting_profile.status
    if consulting == "confirmed":
        score += _W_CONSULTING_CONFIRMED
    elif consulting == "probable":
        score += _W_CONSULTING_PROBABLE
    elif consulting == "no":
        score -= _P_CONSULTING_NO
    breakdown["consulting"] = consulting

    # 3 — long-mission evidence (high). UNKNOWN is neutral (no change).
    mission = evidence.long_mission.status
    if mission == "confirmed":
        score += _W_MISSION_CONFIRMED
    elif mission == "probable":
        score += _W_MISSION_PROBABLE
    elif mission == "no":
        score -= _P_MISSION_NO
    breakdown["long_mission"] = mission

    # 4 — seniority (medium). Only KNOWN experience meeting the bar helps;
    # unknown is neutral.
    if query.min_experience_years is not None:
        years = _total_experience_years(evidence)
        if years is not None and years >= query.min_experience_years:
            score += _W_SENIORITY
            breakdown["seniority"] = f">= {query.min_experience_years}y"
        else:
            breakdown["seniority"] = "unknown" if years is None else f"{years}y"

    # 5 — location (medium).
    if query.location:
        loc = _fold(query.location)
        cand_loc = _fold(evidence.location)
        if cand_loc and loc in cand_loc:
            score += _W_LOCATION
            breakdown["location"] = "match"
        elif cand_loc:
            score -= _P_LOCATION_MISMATCH
            breakdown["location"] = "mismatch"
        else:
            breakdown["location"] = "unknown"

    # 6 — role/title fit (small nudge).
    if query.job_titles and evidence.current_title:
        title = _fold(evidence.current_title)
        if any(_fold(t) in title or title in _fold(t) for t in query.job_titles if t):
            score += _W_ROLE

    return max(0.0, min(1.0, round(score, 4))), breakdown
