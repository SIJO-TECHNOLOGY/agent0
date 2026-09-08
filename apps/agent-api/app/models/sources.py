"""Candidate source selection: the enum and the single resolution rule.

A search may target BoondManager, LinkedIn (public web), or both. The
selection is resolved ONCE (here) and then stored in graph state so routing
is deterministic — no graph node re-derives it, and the LLM can never
override the user's explicit source choice.

Business rules (mandatory):

- ``["boond"]``            -> BoondManager only
- ``["linkedin"]``         -> LinkedIn only
- ``["boond","linkedin"]`` -> both
- ``[]`` or omitted        -> BOTH (BoondManager + LinkedIn) when external
                              search is enabled; BoondManager only otherwise
                              (never resolve to an unavailable source).
"""

from __future__ import annotations

from enum import Enum


class CandidateSource(str, Enum):
    """A discoverable candidate source."""

    BOOND = "boond"
    LINKEDIN = "linkedin"


# Values accepted from the API, mapped to the enum. Kept permissive on input
# (aliases) but the canonical wire value is the enum's own value.
_SOURCE_ALIASES: dict[str, CandidateSource] = {
    "boond": CandidateSource.BOOND,
    "boondmanager": CandidateSource.BOOND,
    "bm": CandidateSource.BOOND,
    "linkedin": CandidateSource.LINKEDIN,
    "linkedin_web": CandidateSource.LINKEDIN,
    "linked-in": CandidateSource.LINKEDIN,
    "web": CandidateSource.LINKEDIN,
    "external": CandidateSource.LINKEDIN,
}


def parse_sources(raw: list[str] | None) -> list[CandidateSource]:
    """Parse raw request source strings into known enum values.

    Unknown tokens are dropped (never raises), so a malformed selection
    degrades to "no source selected" rather than failing the request.
    Order-preserving and de-duplicated.
    """
    if not raw:
        return []
    out: list[CandidateSource] = []
    for item in raw:
        key = str(item).strip().lower()
        source = _SOURCE_ALIASES.get(key)
        if source is not None and source not in out:
            out.append(source)
    return out


def resolve_candidate_sources(
    sources: list[CandidateSource] | list[str] | None,
    *,
    external_search_enabled: bool,
) -> set[CandidateSource]:
    """Resolve the effective set of sources for a search (the single rule).

    ``external_search_enabled`` gates LinkedIn: when off, LinkedIn is removed
    from any resolved set and the empty default falls back to BoondManager
    only, so we never route to a disabled source.
    """
    parsed: list[CandidateSource]
    if sources and isinstance(sources[0], CandidateSource):
        parsed = [s for s in sources if isinstance(s, CandidateSource)]  # type: ignore[list-item]
    else:
        parsed = parse_sources([str(s) for s in (sources or [])])

    if not parsed:
        # No source selected -> BOTH when external is enabled, else Boond only.
        effective = {CandidateSource.BOOND}
        if external_search_enabled:
            effective.add(CandidateSource.LINKEDIN)
        return effective

    effective = set(parsed)
    if not external_search_enabled:
        effective.discard(CandidateSource.LINKEDIN)
    # A selection that resolves to nothing available falls back to Boond.
    if not effective:
        effective = {CandidateSource.BOOND}
    return effective
