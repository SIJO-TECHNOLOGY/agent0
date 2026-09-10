"""Consulting-profile classification for external candidates (SIJO rule).

SIJO prefers consultants. This classifier decides whether a public profile
LOOKS like a consultant/freelance profile, conservatively, preferring evidence
over assumptions:

- confirmed — an explicit consulting/freelance title AND corroborating
              evidence (named client missions, or several distinct missions).
- probable  — consulting/freelance/ESN signals but limited mission detail.
- unknown   — insufficient public data to tell.
- no        — a clear internal-employee profile with enough data and no
              consulting signal at all (assigned conservatively).

An employer NAME alone (e.g. it is a known ESN) is only a weak hint — never
enough on its own to mark a profile ``confirmed`` (per the SIJO rule "do not
classify based purely on employer name").

Pure functions only.
"""

from __future__ import annotations

import re

from app.candidate_sources.linkedin_web.mission_analysis import looks_like_esn
from app.candidate_sources.models import (
    ConsultingProfileEvidence,
    ExternalExperience,
)

_CONSULTING_TITLE_RE = re.compile(
    r"\b(consultant\w*|consulting|conseil|prestataire)\b", re.IGNORECASE
)
_FREELANCE_RE = re.compile(
    r"\b(freelance|free-?lance|independe?nt\w*|ind[eé]pendant\w*|contractor|"
    r"contracting|auto-?entrepreneur|self-?employed|à mon compte)\b",
    re.IGNORECASE,
)


def _title_texts(
    current_title: str | None,
    experiences: list[ExternalExperience],
    snippet: str,
) -> str:
    parts: list[str] = []
    if current_title:
        parts.append(current_title)
    for exp in experiences:
        if exp.title:
            parts.append(exp.title)
        if exp.employer:
            parts.append(exp.employer)
    if snippet:
        parts.append(snippet)
    return " ".join(parts)


def classify_consulting_profile(
    *,
    current_title: str | None,
    experiences: list[ExternalExperience],
    snippet: str = "",
) -> ConsultingProfileEvidence:
    """Classify whether the profile shows consulting experience."""
    haystack = _title_texts(current_title, experiences, snippet)
    evidence: list[str] = []

    consulting_title = bool(_CONSULTING_TITLE_RE.search(current_title or ""))
    consulting_anywhere = bool(_CONSULTING_TITLE_RE.search(haystack))
    freelance = bool(_FREELANCE_RE.search(haystack))
    client_missions = [
        e for e in experiences if e.explicit_client_mission and (e.client or "").strip()
    ]
    consulting_contexts = [e for e in experiences if e.consulting_context]
    esn_employers = [
        e for e in experiences if looks_like_esn(e.employer)
    ]

    if consulting_title:
        evidence.append(f"Title indicates consulting: {current_title!r}")
    elif consulting_anywhere:
        evidence.append("Consulting wording appears in the profile.")
    if freelance:
        evidence.append("Freelance / independent signals present.")
    for exp in client_missions:
        evidence.append(f"Client mission listed: {exp.client}")
    if esn_employers:
        names = ", ".join(sorted({e.employer or "" for e in esn_employers if e.employer}))
        evidence.append(f"Worked at ESN(s): {names}")

    has_any_data = bool(current_title or experiences or snippet.strip())

    # CONFIRMED — explicit consulting/freelance title WITH corroboration
    # (named client missions or multiple distinct missions). Title alone or
    # employer name alone is not enough.
    strong_corroboration = bool(client_missions) or len(consulting_contexts) >= 2
    if (consulting_title or freelance) and strong_corroboration:
        return ConsultingProfileEvidence(status="confirmed", evidence=evidence)

    # PROBABLE — consulting/freelance/ESN signals but limited mission detail.
    if consulting_anywhere or freelance or consulting_contexts or esn_employers:
        return ConsultingProfileEvidence(status="probable", evidence=evidence)

    # NO — a clear profile with data but no consulting signal at all
    # (conservative: needs a title AND at least one experience).
    if current_title and experiences:
        return ConsultingProfileEvidence(
            status="no",
            evidence=["No consulting/freelance/ESN signal in a documented "
                      "internal-employee profile."],
        )

    # UNKNOWN — not enough public information.
    return ConsultingProfileEvidence(
        status="unknown",
        evidence=evidence if has_any_data else [],
    )
