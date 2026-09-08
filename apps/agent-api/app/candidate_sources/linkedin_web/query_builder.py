"""Build a bounded web-search ladder for public LinkedIn discovery.

A single strict query (e.g. every skill quoted together) often excludes great
candidates just because one term is not in the indexed page snippet. So we
generate several COMPLEMENTARY queries — consulting-first, title variants,
skills-oriented, broader geography — bounded by ``max_queries``.

Pure functions only. The order encodes the SIJO preference: consulting intent
first, then role/title, then skills, then a geographic widening.
"""

from __future__ import annotations

from app.candidate_sources.models import CandidateSearchQuery

# site: filter keeps results on LinkedIn member profiles. Web-search engines
# honour it in the query text even when the API also constrains the domain.
_SITE = "site:linkedin.com/in"

# French consulting synonyms appended to broaden the consultant angle without
# the recruiter typing them. Generic — no client/skill hardcoded.
_CONSULTING_TERMS = ("consultant", "freelance", "consultant senior")

# Coarse region widening for common French locations. Best-effort only; an
# unknown location simply skips the geographic-widening pass.
_REGION_WIDENING: dict[str, str] = {
    "nantes": "Pays de la Loire",
    "paris": "Île-de-France",
    "lyon": "Auvergne-Rhône-Alpes",
    "bordeaux": "Nouvelle-Aquitaine",
    "lille": "Hauts-de-France",
    "toulouse": "Occitanie",
    "marseille": "Provence-Alpes-Côte d'Azur",
    "rennes": "Bretagne",
    "nice": "Provence-Alpes-Côte d'Azur",
    "strasbourg": "Grand Est",
}


def _quote(term: str) -> str:
    term = term.strip()
    if not term:
        return ""
    return f'"{term}"' if " " in term else term


def _clean(parts: list[str]) -> str:
    return " ".join(p for p in parts if p).strip()


def build_search_queries(
    query: CandidateSearchQuery, *, max_queries: int = 5
) -> list[str]:
    """Return up to ``max_queries`` complementary LinkedIn-profile searches.

    De-duplicated, order-preserving, consulting-first. Every query includes the
    ``site:linkedin.com/in`` filter so results stay on member profiles.
    """
    titles = [t for t in query.job_titles if t and t.strip()]
    skills = [s for s in query.required_skills if s and s.strip()]
    optional = [s for s in query.optional_skills if s and s.strip()]
    location = (query.location or "").strip()
    companies = [c for c in query.companies if c and c.strip()]

    candidates: list[str] = []

    def add(*parts: str) -> None:
        text = _clean([_SITE, *parts])
        if text and text != _SITE and text not in candidates:
            candidates.append(text)

    primary_title = titles[0] if titles else None
    primary_skill = skills[0] if skills else None

    # 1 — strong consulting intent: "consultant <skill>" [location]
    if query.prefer_consulting_profile:
        anchor = primary_skill or primary_title or (companies[0] if companies else "")
        add(_quote(f"consultant {anchor}".strip()) if anchor else "consultant",
            _quote(location))

    # 2 — title variation (the recruiter's role words), consulting-flavoured.
    if primary_title:
        add(_quote(primary_title), _quote(location))
        if query.prefer_consulting_profile and "consultant" not in primary_title.lower():
            add(_quote(f"{primary_title} consultant"), _quote(location))

    # 3 — skills-oriented: the top required skills together + consulting word.
    if skills:
        skill_terms = " ".join(_quote(s) for s in skills[:3])
        consulting_word = "consultant" if query.prefer_consulting_profile else ""
        add(skill_terms, _quote(location), consulting_word)

    # 4 — company anchor (an ESN/end-client name is highly discriminating).
    for company in companies[:1]:
        add(_quote(company), _quote(primary_skill or primary_title or ""),
            _quote(location))

    # 5 — broader geography (region) to recover profiles indexed by region.
    region = _REGION_WIDENING.get(location.lower()) if location else None
    if region:
        anchor = primary_skill or primary_title or "consultant"
        add(_quote(anchor), _quote(region))

    # 6 — optional-skills fallback broadens recall when the above is thin.
    if optional and len(candidates) < max_queries:
        add(_quote(primary_skill or primary_title or optional[0]),
            " ".join(_quote(s) for s in optional[:2]), _quote(location))

    return candidates[:max_queries]
