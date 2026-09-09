"""Tests for the LinkedInWebSource discovery pipeline with a fake backend.

No network / OpenAI calls: the web-search backend is injected. Covers the
bounded ladder, cross-query dedup, URL validation against cited sources
(rejecting invented URLs), the result cap, integrated qualification, and the
known-candidate profile lookup.
"""

from __future__ import annotations

import pytest

from app.candidate_sources.linkedin_web.source import (
    BackendResult,
    DiscoveryResult,
    LinkedInWebSource,
    _DiscoveredExperience,
    _DiscoveredProfile,
)
from app.candidate_sources.models import CandidateSearchQuery


class FakeBackend:
    """Records prompts and returns scripted results per call."""

    def __init__(self, results: list[BackendResult] | BackendResult) -> None:
        self._results = results if isinstance(results, list) else None
        self._single = results if not isinstance(results, list) else None
        self.prompts: list[str] = []
        self.calls = 0

    async def search(self, prompt: str, schema: type) -> BackendResult:
        self.prompts.append(prompt)
        idx = self.calls
        self.calls += 1
        if self._single is not None:
            return self._single
        if idx < len(self._results):
            return self._results[idx]
        return BackendResult(parsed=DiscoveryResult(profiles=[]), cited_urls=[])


def _profile(url: str, **kw) -> _DiscoveredProfile:
    return _DiscoveredProfile(profile_url=url, **kw)


def _result(profiles: list[_DiscoveredProfile], cited: list[str] | None = None) -> BackendResult:
    return BackendResult(
        parsed=DiscoveryResult(profiles=profiles),
        cited_urls=cited if cited is not None else [p.profile_url for p in profiles],
    )


@pytest.mark.asyncio
async def test_multiple_queries_issued_and_deduped_across_queries() -> None:
    # Every query returns the SAME profile → one candidate after dedup.
    same = _profile(
        "https://www.linkedin.com/in/john-doe",
        full_name="John Doe",
        current_title="Java Consultant",
        matched_skills=["Java"],
    )
    backend = FakeBackend([_result([same]) for _ in range(5)])
    source = LinkedInWebSource(backend, max_queries=5, max_results=20)
    q = CandidateSearchQuery(
        job_titles=["Java Consultant"], required_skills=["Java", "Spring Boot"],
        location="Nantes",
    )
    result = await source.discover(q)
    assert backend.calls >= 2  # a ladder, not a single query
    assert len(result.candidates) == 1
    assert result.metrics["unique_linkedin_urls"] == 1
    assert result.metrics["query_count"] == backend.calls


@pytest.mark.asyncio
async def test_max_queries_respected() -> None:
    backend = FakeBackend([_result([]) for _ in range(10)])
    source = LinkedInWebSource(backend, max_queries=2)
    q = CandidateSearchQuery(
        job_titles=["A", "B"], required_skills=["x", "y", "z"],
        optional_skills=["o1", "o2"], location="Lyon", companies=["ESN"],
    )
    await source.discover(q)
    assert backend.calls <= 2


@pytest.mark.asyncio
async def test_non_profile_urls_rejected() -> None:
    profiles = [
        _profile("https://www.linkedin.com/company/acme", full_name="Acme"),
        _profile("https://www.linkedin.com/in/real-person", full_name="Real Person",
                 matched_skills=["Java"]),
    ]
    backend = FakeBackend(_result(profiles))
    source = LinkedInWebSource(backend, max_queries=1)
    result = await source.discover(CandidateSearchQuery(required_skills=["Java"]))
    urls = [c.evidence.profile_url for c in result.candidates]
    assert urls == ["https://www.linkedin.com/in/real-person"]


@pytest.mark.asyncio
async def test_invented_url_rejected_when_evidence_available() -> None:
    # The model emits a profile URL that is NOT among the search's cited
    # sources → treated as invented and rejected.
    profiles = [_profile("https://www.linkedin.com/in/made-up", full_name="Ghost")]
    backend = FakeBackend(
        BackendResult(
            parsed=DiscoveryResult(profiles=profiles),
            cited_urls=["https://www.linkedin.com/in/someone-else"],
        )
    )
    source = LinkedInWebSource(backend, max_queries=1)
    result = await source.discover(CandidateSearchQuery(required_skills=["Java"]))
    assert result.candidates == []
    assert result.metrics["rejected_count"] >= 1


@pytest.mark.asyncio
async def test_ungrounded_profile_rejected() -> None:
    # A profile with NO cited web sources is treated as invented and rejected
    # (grounding is mandatory) — this is what stops hallucinated profiles.
    profile = _profile("https://www.linkedin.com/in/jane-doe", full_name="Jane Doe",
                        matched_skills=["Java"])
    backend = FakeBackend(
        BackendResult(parsed=DiscoveryResult(profiles=[profile]), cited_urls=[])
    )
    source = LinkedInWebSource(backend, max_queries=1)
    result = await source.discover(CandidateSearchQuery(required_skills=["Java"]))
    assert result.candidates == []
    assert result.metrics["rejected_count"] >= 1


@pytest.mark.asyncio
async def test_missing_terms_do_not_fail_whole_search() -> None:
    # First query returns nothing; a later query returns a candidate.
    good = _profile("https://www.linkedin.com/in/found", full_name="Found",
                    matched_skills=["Java"])
    backend = FakeBackend([_result([]), _result([good]), _result([])])
    source = LinkedInWebSource(backend, max_queries=5)
    q = CandidateSearchQuery(
        job_titles=["Java Consultant"], required_skills=["Java", "Spring Boot"],
        location="Nantes",
    )
    result = await source.discover(q)
    assert len(result.candidates) == 1


@pytest.mark.asyncio
async def test_result_cap_enforced() -> None:
    profiles = [
        _profile(f"https://www.linkedin.com/in/person-{i}", full_name=f"P{i}",
                 matched_skills=["Java"])
        for i in range(10)
    ]
    backend = FakeBackend(_result(profiles))
    source = LinkedInWebSource(backend, max_queries=1, max_results=3)
    result = await source.discover(CandidateSearchQuery(required_skills=["Java"]))
    assert len(result.candidates) == 3


@pytest.mark.asyncio
async def test_qualification_integrated() -> None:
    profile = _profile(
        "https://www.linkedin.com/in/consultant",
        full_name="La Consultante",
        current_title="Senior Java Consultant",
        matched_skills=["Java"],
        experiences=[
            _DiscoveredExperience(
                title="Consultant", client="Airbus",
                explicit_client_mission=True, duration_months=30,
            )
        ],
    )
    backend = FakeBackend(_result([profile]))
    source = LinkedInWebSource(backend, max_queries=1, threshold_months=24)
    result = await source.discover(CandidateSearchQuery(required_skills=["Java"]))
    ev = result.candidates[0].evidence
    assert ev.consulting_profile.status == "confirmed"
    assert ev.long_mission.status == "confirmed"
    assert result.metrics["long_mission_confirmed"] == 1


@pytest.mark.asyncio
async def test_backend_failure_is_isolated_per_query() -> None:
    class FlakyBackend:
        def __init__(self) -> None:
            self.calls = 0

        async def search(self, prompt: str, schema: type) -> BackendResult:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return _result([_profile("https://www.linkedin.com/in/ok",
                                     full_name="Ok", matched_skills=["Java"])])

    source = LinkedInWebSource(FlakyBackend(), max_queries=3)
    q = CandidateSearchQuery(job_titles=["Java Consultant"], required_skills=["Java"],
                             location="Nantes")
    result = await source.discover(q)
    assert result.metrics["failure_count"] >= 1
    assert len(result.candidates) == 1


@pytest.mark.asyncio
async def test_find_profile_for_candidate() -> None:
    profile = _profile(
        "https://www.linkedin.com/in/jean-dupont",
        full_name="Jean Dupont",
        current_title="Java Consultant",
        current_company="Capgemini",
    )
    backend = FakeBackend(_result([profile]))
    source = LinkedInWebSource(backend)
    match = await source.find_profile_for_candidate(
        full_name="Jean Dupont", current_company="Capgemini", job_title="Java Consultant"
    )
    assert match is not None
    assert match.confidence_level == "strong"
    assert match.profile_url == "https://www.linkedin.com/in/jean-dupont"
