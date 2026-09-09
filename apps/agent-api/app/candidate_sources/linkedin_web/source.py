"""External candidate discovery via the OpenAI Responses API web_search tool.

Pipeline (discovery and qualification are DELIBERATELY separate stages):

    CandidateSearchQuery
      -> bounded web-search ladder (query_builder)
      -> OpenAI Responses API web_search (backend, injectable/mockable)
      -> canonicalize + validate URLs against the search's cited sources
      -> dedupe by canonical LinkedIn identifier
      -> consulting qualification + long-mission analysis
      -> score (tri-state) + cap
      -> ScoredExternalCandidate[]

The backend is injected so unit tests never hit the network. The real backend
(`build_openai_backend`) uses `client.responses.parse` with the built-in
`web_search` tool and structured outputs; it reads the citations the search
actually returned so we never trust an LLM-emitted URL that has no evidence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.candidate_sources.linkedin_web.mission_analysis import (
    analyze_long_mission,
    looks_like_esn,
)
from app.candidate_sources.linkedin_web.qualification import (
    classify_consulting_profile,
)
from app.candidate_sources.linkedin_web.query_builder import (
    build_search_queries,
    _quote,
)
from app.candidate_sources.linkedin_web.url_utils import (
    canonical_identifier,
    canonical_profile_url,
    is_profile_url,
)
from app.candidate_sources.models import (
    CandidateSearchQuery,
    ConsultingProfileEvidence,
    Evidence,
    ExternalCandidateEvidence,
    ExternalExperience,
    ExternalProfileMatch,
)
from app.candidate_sources.ranking import score_external_candidate

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# --- Structured-output schemas the model must fill (nothing invented) -------
class _DiscoveredExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    employer: str | None = None
    client: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_months: int | None = None
    consulting_context: bool | None = None
    explicit_client_mission: bool | None = None


class _DiscoveredProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    profile_url: str
    full_name: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    location: str | None = None
    matched_skills: list[str] = Field(default_factory=list)
    experiences: list[_DiscoveredExperience] = Field(default_factory=list)
    snippet: str = ""


class DiscoveryResult(BaseModel):
    """Top-level structured output for one discovery web search."""

    model_config = ConfigDict(extra="ignore")
    profiles: list[_DiscoveredProfile] = Field(default_factory=list)


@dataclass(frozen=True)
class BackendResult:
    """A backend's parsed output plus the URLs the search actually cited."""

    parsed: BaseModel
    cited_urls: list[str] = field(default_factory=list)


class WebSearchBackend(Protocol):
    """Runs one structured web search. Injected so tests never hit the network."""

    async def search(self, prompt: str, schema: type[T]) -> BackendResult: ...


@dataclass
class ScoredExternalCandidate:
    evidence: ExternalCandidateEvidence
    score: float
    breakdown: dict[str, object] = field(default_factory=dict)


@dataclass
class ExternalDiscoveryResult:
    candidates: list[ScoredExternalCandidate] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)


_DISCOVERY_SYSTEM = (
    "You are a sourcing assistant that finds PUBLIC LinkedIn member profiles "
    "(linkedin.com/in/...) matching a recruiter's brief, using web search. "
    "Rules you must follow strictly:\n"
    "- Only return profiles you actually found via web search; never guess or "
    "construct a profile URL from a name.\n"
    "- If web search returns no relevant public profile, return an EMPTY "
    "profiles list. Never fabricate a profile and never use placeholder names "
    "such as 'Jane Doe' or 'John Smith'.\n"
    "- Use null for any field you cannot see in public data; never invent "
    "values.\n"
    "- Distinguish EMPLOYER (who paid the person) from CLIENT (the end customer "
    "of a mission). Set explicit_client_mission=true ONLY when the profile "
    "clearly names a client for that line; otherwise false/null.\n"
    "- Set consulting_context=true when the line is a consulting/ESN/freelance "
    "engagement.\n"
    "- duration_months is the length of THAT line only."
)


def _discovery_prompt(search_query: str, query: CandidateSearchQuery) -> str:
    wants = []
    if query.job_titles:
        wants.append("titles: " + ", ".join(query.job_titles[:4]))
    if query.required_skills:
        wants.append("required skills: " + ", ".join(query.required_skills))
    if query.optional_skills:
        wants.append("nice-to-have: " + ", ".join(query.optional_skills))
    if query.location:
        wants.append("location: " + query.location)
    if query.prefer_consulting_profile:
        wants.append("prefer consultant/freelance profiles")
    brief = "; ".join(wants) if wants else "(no extra criteria)"
    # The web_search tool does its own searching, so a raw `site:` string is a
    # poor instruction — it works far better with natural language. We strip
    # the `site:`/quotes and keep the ladder pass's terms as the focus.
    focus = search_query.replace("site:linkedin.com/in", "").replace('"', " ")
    focus = " ".join(focus.split()).strip()
    return (
        "Using web search, find REAL public LinkedIn member profiles "
        "(linkedin.com/in/...) matching this search"
        + (f", focusing on: {focus}." if focus else ".")
        + f"\nCriteria: {brief}."
        + "\nList each person you actually find, with their linkedin.com/in URL. "
        "If you find none, return an empty list — never invent a profile."
    )


class LinkedInWebSource:
    """Discover external candidates from public LinkedIn pages."""

    def __init__(
        self,
        backend: WebSearchBackend,
        *,
        max_queries: int = 5,
        max_results: int = 20,
        linkedin_only: bool = True,
        threshold_months: int = 24,
        prefer_consulting_profile: bool = True,
    ) -> None:
        self._backend = backend
        self._max_queries = max_queries
        self._max_results = max_results
        self._linkedin_only = linkedin_only
        self._threshold_months = threshold_months
        self._prefer_consulting = prefer_consulting_profile

    async def discover(self, query: CandidateSearchQuery) -> ExternalDiscoveryResult:
        queries = build_search_queries(query, max_queries=self._max_queries)
        seen: dict[str, ExternalCandidateEvidence] = {}
        rejected = 0
        failures = 0
        start = time.perf_counter()

        for search_query in queries:
            try:
                result = await self._backend.search(
                    _discovery_prompt(search_query, query), DiscoveryResult
                )
            except Exception as exc:  # noqa: BLE001 — one failed query is non-fatal
                logger.warning(
                    "linkedin_web.query_failed",
                    extra={"query": search_query, "error": str(exc)[:500]},
                )
                failures += 1
                continue

            parsed = result.parsed
            if not isinstance(parsed, DiscoveryResult):
                continue
            logger.info(
                "linkedin_web.query_done",
                extra={
                    "query": search_query,
                    "profiles_returned": len(parsed.profiles),
                    "cited_urls": len(result.cited_urls),
                },
            )
            cited_ids = {
                cid
                for cid in (canonical_identifier(u) for u in result.cited_urls)
                if cid
            }
            for profile in parsed.profiles:
                evidence = self._validate_and_build(profile, query, cited_ids)
                if evidence is None:
                    rejected += 1
                    continue
                ident = canonical_identifier(evidence.profile_url)
                if ident is None:
                    rejected += 1
                    continue
                if ident in seen:
                    _merge_matched_skills(seen[ident], evidence)
                    continue
                seen[ident] = evidence

        scored = [
            ScoredExternalCandidate(evidence=ev, score=score, breakdown=bd)
            for ev in seen.values()
            for score, bd in (score_external_candidate(ev, query),)
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        scored = scored[: self._max_results]

        latency_ms = int((time.perf_counter() - start) * 1000)
        metrics = _build_metrics(
            query_count=len(queries),
            candidates=scored,
            rejected=rejected,
            failures=failures,
            latency_ms=latency_ms,
        )
        logger.info("linkedin_web.discover", extra=metrics)
        return ExternalDiscoveryResult(candidates=scored, metrics=metrics)

    async def find_profile_for_candidate(
        self,
        *,
        full_name: str,
        current_company: str | None = None,
        previous_company: str | None = None,
        job_title: str | None = None,
        location: str | None = None,
    ) -> "ExternalProfileMatch | None":
        """Find a known candidate's public LinkedIn profile by identity clues.

        Returns the best graded match, or None when nothing plausible is found.
        Never auto-merges: the caller decides what to do with a ``probable`` /
        ``ambiguous`` result (only ``strong`` should be treated as the same
        person).
        """
        from app.candidate_sources.linkedin_web.identity import score_profile_match

        terms = " ".join(
            _quote(part)
            for part in (full_name, current_company, job_title, location)
            if part and part.strip()
        )
        prompt = (
            "Find the single public LinkedIn member profile for this person. "
            f"Name: {full_name}. "
            f"Company: {current_company or 'unknown'}. "
            f"Previous company: {previous_company or 'unknown'}. "
            f"Title: {job_title or 'unknown'}. "
            f"Location: {location or 'unknown'}. "
            f"Web search: site:linkedin.com/in {terms}"
        )
        try:
            result = await self._backend.search(prompt, DiscoveryResult)
        except Exception:  # noqa: BLE001 — non-fatal lookup
            logger.warning("linkedin_web.identity_lookup_failed")
            return None
        parsed = result.parsed
        if not isinstance(parsed, DiscoveryResult) or not parsed.profiles:
            return None
        cited_ids = {
            cid for cid in (canonical_identifier(u) for u in result.cited_urls) if cid
        }
        best: ExternalProfileMatch | None = None
        for profile in parsed.profiles:
            url = (profile.profile_url or "").strip()
            if self._linkedin_only and not is_profile_url(url):
                continue
            canon = canonical_profile_url(url)
            if canon is None:
                continue
            if cited_ids and canonical_identifier(url) not in cited_ids:
                continue
            match = score_profile_match(
                known_name=full_name,
                known_company=current_company,
                known_previous_company=previous_company,
                known_title=job_title,
                known_location=location,
                profile_url=canon,
                profile_name=profile.full_name,
                profile_company=profile.current_company,
                profile_title=profile.current_title,
                profile_location=profile.location,
            )
            if best is None or match.score > best.score:
                best = match
        return best

    def _validate_and_build(
        self,
        profile: _DiscoveredProfile,
        query: CandidateSearchQuery,
        cited_ids: set[str],
    ) -> ExternalCandidateEvidence | None:
        url = (profile.profile_url or "").strip()
        if self._linkedin_only and not is_profile_url(url):
            return None
        canon = canonical_profile_url(url)
        if canon is None:
            return None
        ident = canonical_identifier(url)
        # Grounding is MANDATORY: accept a profile ONLY if the web search
        # actually cited its URL. If the search reported no sources, or this
        # URL is not among them, the profile was not genuinely found — treat it
        # as invented and reject it. This is what stops hallucinated
        # "Jane Doe"-style profiles from a model that fills the schema without
        # real web results. Never trust an LLM-emitted URL on its own.
        if not cited_ids or ident not in cited_ids:
            logger.info(
                "linkedin_web.url_unsupported",
                extra={"url": url, "cited_count": len(cited_ids)},
            )
            return None

        experiences = [
            ExternalExperience(
                title=e.title,
                employer=e.employer,
                client=e.client,
                start_date=e.start_date,
                end_date=e.end_date,
                duration_months=e.duration_months,
                # Weak ESN hint if the model didn't already flag consulting.
                consulting_context=(
                    e.consulting_context
                    if e.consulting_context is not None
                    else (True if looks_like_esn(e.employer) else None)
                ),
                explicit_client_mission=e.explicit_client_mission,
            )
            for e in profile.experiences
        ]
        consulting: ConsultingProfileEvidence = classify_consulting_profile(
            current_title=profile.current_title,
            experiences=experiences,
            snippet=profile.snippet,
        )
        long_mission = analyze_long_mission(
            experiences,
            threshold_months=self._threshold_months,
            consulting_status=consulting.status,
        )
        evidence = _grounded_evidence(profile, canon)
        return ExternalCandidateEvidence(
            profile_url=canon,
            full_name=profile.full_name,
            current_title=profile.current_title,
            current_company=profile.current_company,
            location=profile.location,
            matched_skills=[s for s in profile.matched_skills if s and s.strip()],
            experiences=experiences,
            consulting_profile=consulting,
            long_mission=long_mission,
            evidence=evidence,
            snippet=profile.snippet,
        )


def _grounded_evidence(
    profile: _DiscoveredProfile, source_url: str
) -> list[Evidence]:
    out: list[Evidence] = []
    if profile.current_title:
        out.append(Evidence(field="current_title", value=profile.current_title, source_url=source_url))
    if profile.current_company:
        out.append(Evidence(field="current_company", value=profile.current_company, source_url=source_url))
    if profile.location:
        out.append(Evidence(field="location", value=profile.location, source_url=source_url))
    return out


def _merge_matched_skills(
    target: ExternalCandidateEvidence, extra: ExternalCandidateEvidence
) -> None:
    seen = {s.lower() for s in target.matched_skills}
    for skill in extra.matched_skills:
        if skill.lower() not in seen:
            target.matched_skills.append(skill)
            seen.add(skill.lower())


def _build_metrics(
    *,
    query_count: int,
    candidates: list[ScoredExternalCandidate],
    rejected: int,
    failures: int,
    latency_ms: int,
) -> dict[str, object]:
    def _count(getter) -> int:
        return sum(1 for c in candidates if getter(c.evidence))

    return {
        "query_count": query_count,
        "result_count": len(candidates),
        "unique_linkedin_urls": len({c.evidence.profile_url for c in candidates}),
        "rejected_count": rejected,
        "failure_count": failures,
        "consulting_confirmed": _count(
            lambda e: e.consulting_profile.status == "confirmed"
        ),
        "consulting_probable": _count(
            lambda e: e.consulting_profile.status == "probable"
        ),
        "long_mission_confirmed": _count(
            lambda e: e.long_mission.status == "confirmed"
        ),
        "long_mission_probable": _count(
            lambda e: e.long_mission.status == "probable"
        ),
        "long_mission_unknown": _count(
            lambda e: e.long_mission.status == "unknown"
        ),
        "latency_ms": latency_ms,
    }
