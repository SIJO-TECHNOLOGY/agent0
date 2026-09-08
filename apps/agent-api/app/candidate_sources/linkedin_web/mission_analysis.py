"""Long-mission analysis for external candidates (SIJO business rule).

The core SIJO criterion is: does the candidate show at least ONE client
mission lasting >= the configured threshold (default 24 months)?

The critical distinction — enforced here — is:

    EMPLOYMENT duration at one employer  !=  one CLIENT-MISSION duration

"Capgemini 2018 → 2025" proves 7 years EMPLOYED at Capgemini. It does NOT
prove one 84-month mission for a single client; a consultant typically rotates
across several missions. So a long employer tenure with no named client can be
at most ``probable`` (when the profile is clearly a consultant), never
``confirmed``.

Statuses:
- confirmed — an explicit client mission (client named) >= threshold.
- probable  — consultant/ESN context + a long period >= threshold, but the
              single-client mission cannot be proven.
- unknown   — public data is insufficient (missing dates/durations).
- no        — enough dated missions exist and all are shorter than threshold.

Pure functions only.
"""

from __future__ import annotations

import re

from app.candidate_sources.models import (
    EvidenceStatus,
    ExternalExperience,
    LongMissionEvidence,
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "aout": 8, "août": 8, "sept": 9,
    "octo": 10, "nove": 11, "dece": 12, "déce": 12,
}

# "present"/"current" end dates — treated as an OPEN mission we cannot bound
# from static data, so they never contribute a confirmed duration on their own.
_PRESENT_RE = re.compile(
    r"\b(present|current|aujourd|actuel|now|ongoing|en cours)\b", re.IGNORECASE
)


def _parse_month_year(text: str | None) -> tuple[int, int] | None:
    """Parse a loose date string into (year, month). Month defaults to 1."""
    if not text or not isinstance(text, str):
        return None
    if _PRESENT_RE.search(text):
        return None
    lowered = text.strip().lower()
    # Numeric YYYY-MM or MM/YYYY or YYYY.
    m = re.search(r"(\d{4})[-/.](\d{1,2})", lowered)
    if m:
        return int(m.group(1)), max(1, min(12, int(m.group(2))))
    m = re.search(r"(\d{1,2})[-/.](\d{4})", lowered)
    if m:
        return int(m.group(2)), max(1, min(12, int(m.group(1))))
    # Month name + year.
    m = re.search(r"([a-zéûôà]+)\.?\s+(\d{4})", lowered)
    if m:
        month = _MONTHS.get(m.group(1)[:4]) or _MONTHS.get(m.group(1)[:3])
        if month:
            return int(m.group(2)), month
    # Bare year.
    m = re.search(r"\b(\d{4})\b", lowered)
    if m:
        return int(m.group(1)), 1
    return None


def months_between(start: str | None, end: str | None) -> int | None:
    """Robust month duration between two loose date strings, or None.

    Returns None when either end cannot be parsed (e.g. missing dates, or an
    open "present" end) so callers can treat it as UNKNOWN rather than 0.
    """
    start_ym = _parse_month_year(start)
    end_ym = _parse_month_year(end)
    if start_ym is None or end_ym is None:
        return None
    months = (end_ym[0] - start_ym[0]) * 12 + (end_ym[1] - start_ym[1])
    return months if months >= 0 else None


def experience_duration_months(exp: ExternalExperience) -> int | None:
    """Best-known duration for an experience: explicit value, else computed."""
    if exp.duration_months is not None and exp.duration_months >= 0:
        return exp.duration_months
    return months_between(exp.start_date, exp.end_date)


def analyze_long_mission(
    experiences: list[ExternalExperience],
    *,
    threshold_months: int,
    consulting_status: EvidenceStatus | None = None,
) -> LongMissionEvidence:
    """Classify long-mission evidence conservatively.

    ``consulting_status`` (from the consulting classifier) lets a long tenure
    at an unnamed employer reach ``probable`` when the profile is clearly a
    consultant — but never ``confirmed`` without a named client mission.
    """
    # CONFIRMED — an explicit client mission, client named, >= threshold.
    confirmed: list[tuple[int, ExternalExperience]] = []
    # PROBABLE — consulting context, long period, no provable single client.
    probable: list[tuple[int, ExternalExperience]] = []
    dated_durations: list[int] = []

    for exp in experiences:
        dur = experience_duration_months(exp)
        if dur is None:
            continue
        dated_durations.append(dur)
        if dur < threshold_months:
            continue
        if exp.explicit_client_mission and (exp.client or "").strip():
            confirmed.append((dur, exp))
        elif exp.consulting_context or (consulting_status in ("confirmed", "probable")):
            probable.append((dur, exp))

    if confirmed:
        dur, exp = max(confirmed, key=lambda pair: pair[0])
        return LongMissionEvidence(
            status="confirmed",
            max_duration_months=dur,
            employer=exp.employer,
            client=exp.client,
            evidence_text=(
                f"Client mission at {exp.client} (~{dur} months) documented "
                "on the public profile."
            ),
        )

    if probable:
        dur, exp = max(probable, key=lambda pair: pair[0])
        return LongMissionEvidence(
            status="probable",
            max_duration_months=dur,
            employer=exp.employer,
            client=exp.client,
            evidence_text=(
                f"~{dur} months in a consulting/ESN context at "
                f"{exp.employer or 'an employer'}, but no single client "
                "mission of that length is provable from public data."
            ),
        )

    # A long tenure exists but with no consulting context and no named client:
    # employer duration is NOT a client mission — cannot confirm.
    long_tenures = [d for d in dated_durations if d >= threshold_months]
    if long_tenures:
        return LongMissionEvidence(
            status="unknown",
            max_duration_months=max(long_tenures),
            evidence_text=(
                "A long employer tenure is visible, but public data does not "
                "show it was a single client mission of that length."
            ),
        )

    # NO — enough dated missions and all shorter than threshold.
    _SUFFICIENT_HISTORY = 2
    if len(dated_durations) >= _SUFFICIENT_HISTORY:
        return LongMissionEvidence(
            status="no",
            max_duration_months=max(dated_durations) if dated_durations else None,
            evidence_text=(
                "All documented missions are shorter than the threshold."
            ),
        )

    # Not enough public information to conclude anything.
    return LongMissionEvidence(status="unknown")


# A small, non-exhaustive list of well-known French ESNs used ONLY as a weak
# consulting-context hint (never as sole proof of a consultant profile).
KNOWN_ESN_NAMES: frozenset[str] = frozenset(
    {
        "capgemini", "sopra steria", "sopra", "atos", "cgi", "accenture",
        "devoteam", "sogeti", "inetum", "gfi", "alten", "akka", "expleo",
        "wavestone", "talan", "mc2i", "onepoint", "umanis", "keyrus",
        "sqli", "hardis", "aubay", "neoxia", "octo", "ippon", "zenika",
    }
)


def looks_like_esn(employer: str | None) -> bool:
    """True when the employer name matches a known ESN (weak hint only)."""
    if not employer:
        return False
    low = employer.strip().lower()
    return any(esn in low for esn in KNOWN_ESN_NAMES)
