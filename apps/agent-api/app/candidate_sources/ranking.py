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

import re
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
_W_ROLE: Final[float] = 0.05
# Location tiers (medium-high): a same-region match is a strong preference,
# a same francophone area is a mild plus, a clearly-foreign location is a
# solid demotion (but never an exclusion — "preferably local", and an unknown
# location stays neutral, never penalised).
_W_LOCATION_REGION: Final[float] = 0.12
_W_LOCATION_FRANCOPHONE: Final[float] = 0.04
# The real minimum bar (per SIJO): the candidate speaks French AND has had an
# experience in France — regardless of nationality or current country.
_W_FRENCH: Final[float] = 0.08
_W_FRANCE_EXPERIENCE: Final[float] = 0.10
# Intrinsic "preferably in Île-de-France" nudge, applied whenever the candidate
# is based in IDF, independent of the requested location.
_W_IDF_INTRINSIC: Final[float] = 0.05

# Negative weights — applied only for CONFIRMED-negative evidence.
_P_CONSULTING_NO: Final[float] = 0.10
_P_MISSION_NO: Final[float] = 0.12
# A clearly-foreign CURRENT location is heavily demoted ONLY when the profile
# shows neither French nor a France experience (a French-speaking candidate who
# worked in France is fine even if based abroad now).
_P_LOCATION_FOREIGN: Final[float] = 0.30

# Accent-folded location markers. France / Île-de-France places (region match
# when the requested location is in France), the broader French-speaking area
# (mild preference), and clearly non-francophone places (demotion). The
# foreign set is not exhaustive — an unrecognised location stays UNKNOWN
# (neutral), so we never wrongly penalise a profile whose location we can't
# place.
_FRANCE_IDF_MARKERS: Final[frozenset[str]] = frozenset({
    "france", "ile-de-france", "ile de france", "idf", "paris", "nanterre",
    "boulogne", "versailles", "creteil", "saint-denis", "montreuil", "issy",
    "levallois", "courbevoie", "la defense", "defense", "hauts-de-seine",
    "seine-saint-denis", "val-de-marne", "val-d'oise", "val-d oise",
    "yvelines", "essonne", "seine-et-marne", "cergy", "massy", "saclay",
})
_IDF_ONLY_MARKERS: Final[frozenset[str]] = frozenset({
    "ile-de-france", "ile de france", "idf", "paris", "nanterre", "boulogne",
    "versailles", "creteil", "saint-denis", "montreuil", "issy", "levallois",
    "courbevoie", "la defense", "defense", "hauts-de-seine",
    "seine-saint-denis", "val-de-marne", "val-d'oise", "val-d oise",
    "yvelines", "essonne", "seine-et-marne", "cergy", "massy", "saclay",
})
_FRANCOPHONE_MARKERS: Final[frozenset[str]] = frozenset({
    "france", "belgique", "belgium", "bruxelles", "brussels", "wallonie",
    "luxembourg", "suisse", "switzerland", "geneve", "geneva", "lausanne",
    "monaco", "quebec", "montreal", "maroc", "morocco", "casablanca",
    "tunisie", "tunisia", "tunis", "algerie", "algeria", "alger",
    "senegal", "dakar", "cote d'ivoire", "cote d ivoire", "abidjan",
})
_FOREIGN_MARKERS: Final[frozenset[str]] = frozenset({
    "romania", "roumanie", "bucharest", "bucuresti", "cluj",
    "india", "inde", "bangalore", "bengaluru", "mumbai", "delhi", "pune",
    "hyderabad", "chennai", "noida", "gurgaon",
    "poland", "pologne", "warsaw", "varsovie", "krakow", "wroclaw",
    "germany", "allemagne", "deutschland", "berlin", "munich", "frankfurt",
    "spain", "espagne", "madrid", "barcelona", "barcelone", "valencia",
    "italy", "italie", "milan", "milano", "rome", "roma", "torino",
    "portugal", "lisbon", "lisbonne", "porto",
    "united kingdom", "london", "londres", "england", "manchester",
    "united states", "new york", "san francisco", "seattle", "austin",
    "netherlands", "amsterdam", "pays-bas", "rotterdam",
    "ukraine", "kyiv", "kiev", "lviv",
    "brazil", "bresil", "sao paulo",
    "pakistan", "lahore", "karachi", "islamabad",
    "turkey", "turquie", "istanbul", "egypt", "egypte", "cairo",
})


def _has_marker(text: str, markers: frozenset[str]) -> bool:
    return any(m in text for m in markers)


def _location_relevance(requested: str, candidate: str | None) -> str:
    """Classify a candidate's location vs the requested one.

    Returns ``match`` (same place/region), ``francophone`` (French-speaking
    area when the request is in France), ``foreign`` (recognised non-francophone
    place), or ``unknown`` (no location, or unrecognised — stays neutral).
    """
    cand = _fold(candidate)
    if not cand:
        return "unknown"
    req = _fold(requested)
    req_tokens = [t for t in re.split(r"[^a-z0-9]+", req) if len(t) >= 3]
    if req and (req in cand or any(t in cand for t in req_tokens)):
        return "match"
    requested_is_france = _has_marker(req, _FRANCE_IDF_MARKERS) or any(
        t in _FRANCE_IDF_MARKERS for t in req_tokens
    )
    if requested_is_france:
        if _has_marker(cand, _FRANCE_IDF_MARKERS):
            return "match"
        if _has_marker(cand, _FRANCOPHONE_MARKERS):
            return "francophone"
        if _has_marker(cand, _FOREIGN_MARKERS):
            return "foreign"
        return "unknown"
    # Generic case: only demote when we recognise a foreign place.
    return "foreign" if _has_marker(cand, _FOREIGN_MARKERS) else "unknown"


def _speaks_french(evidence: ExternalCandidateEvidence) -> bool:
    """True when the profile evidences French (language list or francophone place)."""
    for lang in evidence.languages:
        folded = _fold(lang)
        # "franc" covers français / francais / francophone; "french" is the
        # English spelling; "fr" the bare code.
        if "franc" in folded or "french" in folded or folded == "fr":
            return True
    if _has_marker(_fold(evidence.location), _FRANCOPHONE_MARKERS):
        return True
    return any(
        _has_marker(_fold(exp.location), _FRANCOPHONE_MARKERS)
        for exp in evidence.experiences
    )


def _has_france_experience(evidence: ExternalCandidateEvidence) -> bool:
    """True when a role took place in France (or the person is based there)."""
    if _has_marker(_fold(evidence.location), _FRANCE_IDF_MARKERS):
        return True
    return any(
        _has_marker(_fold(exp.location), _FRANCE_IDF_MARKERS)
        for exp in evidence.experiences
    )


def speaks_french(evidence: ExternalCandidateEvidence) -> bool:
    """Public: does the profile evidence French (language or francophone place)?"""
    return _speaks_french(evidence)


def has_france_experience(evidence: ExternalCandidateEvidence) -> bool:
    """Public: does the profile evidence an experience in France?"""
    return _has_france_experience(evidence)


def is_ineligible_foreign(evidence: ExternalCandidateEvidence) -> bool:
    """True for a clearly-foreign profile with NO French AND NO France experience.

    Conservative by design (UNKNOWN != NO): excludes ONLY when the current
    location matches a recognised foreign country/city marker AND the profile
    evidences neither French nor an experience in France. A profile whose
    location we cannot place, or that speaks French, or that worked in France,
    is never excluded here.
    """
    if _speaks_french(evidence) or _has_france_experience(evidence):
        return False
    return _has_marker(_fold(evidence.location), _FOREIGN_MARKERS)


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

    # 5a — the SIJO minimum bar: French-speaking AND some experience in France
    # (nationality / current country don't matter). Evidenced signals boost;
    # unknown stays neutral (we can't prove absence from sparse public data).
    speaks_fr = _speaks_french(evidence)
    fr_exp = _has_france_experience(evidence)
    if speaks_fr:
        score += _W_FRENCH
        breakdown["french"] = True
    if fr_exp:
        score += _W_FRANCE_EXPERIENCE
        breakdown["france_experience"] = True

    # 5b — location tier vs the requested place. A clearly-foreign CURRENT
    # location is demoted ONLY when the profile shows neither French nor a
    # France experience — so a francophone candidate who worked in France is
    # kept even if based abroad now. Unknown stays neutral.
    if query.location:
        rel = _location_relevance(query.location, evidence.location)
        breakdown["location"] = rel
        if rel == "match":
            score += _W_LOCATION_REGION
        elif rel == "francophone":
            score += _W_LOCATION_FRANCOPHONE
        elif rel == "foreign" and not (speaks_fr or fr_exp):
            score -= _P_LOCATION_FOREIGN

    # 5c — intrinsic "preferably in Île-de-France" nudge (independent of the
    # requested location, so IDF is preferred even for a broad "France" query).
    if _has_marker(_fold(evidence.location), _IDF_ONLY_MARKERS):
        score += _W_IDF_INTRINSIC
        breakdown["idf"] = True

    # 6 — role/title fit (small nudge).
    if query.job_titles and evidence.current_title:
        title = _fold(evidence.current_title)
        if any(_fold(t) in title or title in _fold(t) for t in query.job_titles if t):
            score += _W_ROLE

    return max(0.0, min(1.0, round(score, 4))), breakdown
