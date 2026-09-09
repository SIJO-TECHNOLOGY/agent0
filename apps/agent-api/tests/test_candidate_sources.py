"""Unit tests for provider-neutral candidate-source logic (pure functions).

Covers: source resolution, LinkedIn URL handling, the discovery query ladder,
consultant qualification, long-mission classification (incl. the mandatory
employer!=mission rule), identity matching, tri-state ranking, and cross-source
merge/dedup.
"""

from __future__ import annotations

from app.candidate_sources.linkedin_web.identity import score_profile_match
from app.candidate_sources.linkedin_web.mission_analysis import (
    analyze_long_mission,
    months_between,
)
from app.candidate_sources.linkedin_web.qualification import (
    classify_consulting_profile,
)
from app.candidate_sources.linkedin_web.query_builder import build_search_queries
from app.candidate_sources.linkedin_web.url_utils import (
    canonical_identifier,
    canonical_profile_url,
    is_profile_url,
)
from app.candidate_sources.merge import merge_candidate_cards
from app.candidate_sources.models import (
    CandidateSearchQuery,
    ConsultingProfileEvidence,
    ExternalCandidateEvidence,
    ExternalExperience,
    LongMissionEvidence,
)
from app.candidate_sources.ranking import score_external_candidate
from app.models.api import CandidateCard
from app.models.sources import CandidateSource, resolve_candidate_sources

B = CandidateSource.BOOND
L = CandidateSource.LINKEDIN


# --- 34: source selection resolution ---------------------------------------
def test_sources_omitted_resolves_to_both_when_enabled() -> None:
    assert resolve_candidate_sources(None, external_search_enabled=True) == {B, L}


def test_sources_empty_resolves_to_both_when_enabled() -> None:
    assert resolve_candidate_sources([], external_search_enabled=True) == {B, L}


def test_sources_boond_only() -> None:
    assert resolve_candidate_sources(["boond"], external_search_enabled=True) == {B}


def test_sources_linkedin_only() -> None:
    assert resolve_candidate_sources(["linkedin"], external_search_enabled=True) == {L}


def test_sources_both() -> None:
    assert resolve_candidate_sources(
        ["boond", "linkedin"], external_search_enabled=True
    ) == {B, L}


def test_external_disabled_omitted_resolves_to_boond_only() -> None:
    assert resolve_candidate_sources(None, external_search_enabled=False) == {B}


def test_external_disabled_linkedin_only_falls_back_to_boond() -> None:
    # A request for a disabled source must not route to it.
    assert resolve_candidate_sources(["linkedin"], external_search_enabled=False) == {B}


def test_unknown_source_token_ignored() -> None:
    assert resolve_candidate_sources(["carrierpigeon"], external_search_enabled=True) == {B, L}


# --- 36: LinkedIn URL handling ----------------------------------------------
def test_profile_url_accepted() -> None:
    assert is_profile_url("https://www.linkedin.com/in/john-doe")
    assert is_profile_url("linkedin.com/in/john-doe")


def test_profile_url_normalised() -> None:
    assert (
        canonical_profile_url("https://www.linkedin.com/in/john-doe/")
        == "https://www.linkedin.com/in/john-doe"
    )


def test_company_jobs_posts_pulse_rejected() -> None:
    assert not is_profile_url("https://www.linkedin.com/company/acme")
    assert not is_profile_url("https://www.linkedin.com/jobs/view/123")
    assert not is_profile_url("https://www.linkedin.com/posts/foo-bar")
    assert not is_profile_url("https://www.linkedin.com/pulse/some-article")


def test_non_linkedin_host_rejected() -> None:
    assert not is_profile_url("https://example.com/in/john-doe")


def test_tracking_params_and_region_dedupe_to_same_identifier() -> None:
    a = canonical_profile_url("https://www.linkedin.com/in/john-doe/?trk=public_profile")
    b = canonical_profile_url("https://fr.linkedin.com/in/john-doe")
    assert a == b == "https://www.linkedin.com/in/john-doe"
    assert canonical_identifier("https://www.linkedin.com/in/john-doe/") == "john-doe"


# --- 37: search ladder ------------------------------------------------------
def test_query_ladder_generates_multiple_complementary_queries() -> None:
    q = CandidateSearchQuery(
        job_titles=["Java Consultant", "Backend Developer"],
        required_skills=["Java", "Spring Boot"],
        optional_skills=["Kubernetes", "AWS"],
        location="Nantes",
    )
    queries = build_search_queries(q, max_queries=5)
    assert 2 <= len(queries) <= 5
    assert all("site:linkedin.com/in" in query for query in queries)
    assert len(set(queries)) == len(queries)  # de-duplicated


def test_query_ladder_respects_max() -> None:
    q = CandidateSearchQuery(
        job_titles=["A", "B"],
        required_skills=["x", "y", "z"],
        optional_skills=["o1", "o2"],
        location="Lyon",
        companies=["ESN"],
    )
    assert len(build_search_queries(q, max_queries=3)) <= 3


def test_query_ladder_widens_geography() -> None:
    q = CandidateSearchQuery(required_skills=["Java"], location="Nantes")
    queries = build_search_queries(q, max_queries=6)
    assert any("Pays de la Loire" in query for query in queries)


# --- 38: consultant qualification -------------------------------------------
def test_consultant_confirmed() -> None:
    ev = classify_consulting_profile(
        current_title="Senior Java Consultant",
        experiences=[
            ExternalExperience(
                title="Consultant", client="Airbus", explicit_client_mission=True
            )
        ],
    )
    assert ev.status == "confirmed"


def test_consultant_probable() -> None:
    ev = classify_consulting_profile(
        current_title="Senior Consultant",
        experiences=[ExternalExperience(employer="ESN X", consulting_context=True)],
    )
    assert ev.status == "probable"


def test_consultant_unknown_when_no_data() -> None:
    ev = classify_consulting_profile(current_title=None, experiences=[])
    assert ev.status == "unknown"


def test_non_consulting_profile_is_no() -> None:
    ev = classify_consulting_profile(
        current_title="Software Engineer",
        experiences=[
            ExternalExperience(title="Software Engineer", employer="Google", duration_months=60)
        ],
    )
    assert ev.status == "no"


# --- 39: long-mission classification ----------------------------------------
def test_long_mission_confirmed_explicit_client() -> None:
    ev = analyze_long_mission(
        [ExternalExperience(client="Airbus", explicit_client_mission=True, duration_months=30)],
        threshold_months=24,
    )
    assert ev.status == "confirmed"
    assert ev.max_duration_months == 30


def test_long_mission_probable_esn_no_client() -> None:
    ev = analyze_long_mission(
        [ExternalExperience(employer="ESN X", consulting_context=True, duration_months=40)],
        threshold_months=24,
    )
    assert ev.status == "probable"


def test_long_mission_unknown_when_dates_missing() -> None:
    ev = analyze_long_mission(
        [ExternalExperience(title="Developer")], threshold_months=24
    )
    assert ev.status == "unknown"


def test_long_mission_no_when_all_short_with_history() -> None:
    ev = analyze_long_mission(
        [
            ExternalExperience(duration_months=6),
            ExternalExperience(duration_months=12),
            ExternalExperience(duration_months=18),
        ],
        threshold_months=24,
    )
    assert ev.status == "no"


def test_long_mission_threshold_edges() -> None:
    def status(months: int) -> str:
        return analyze_long_mission(
            [ExternalExperience(client="X", explicit_client_mission=True, duration_months=months)],
            threshold_months=24,
        ).status

    assert status(23) != "confirmed"
    assert status(24) == "confirmed"
    assert status(25) == "confirmed"


def test_months_between_robust() -> None:
    assert months_between("2018", "2025") == 84
    assert months_between("Jan 2021", "Aug 2023") == 31
    assert months_between("2021-01", "2021-12") == 11
    assert months_between("2021", "present") is None  # open end -> unknown


# --- 40: employer duration != client mission duration (MANDATORY) -----------
def test_long_employer_tenure_never_confirmed_without_client() -> None:
    # Capgemini 2018 -> 2025, no client evidence: MUST NOT be a confirmed
    # 84-month mission. At most probable (with consulting evidence).
    exp = ExternalExperience(employer="Capgemini", start_date="2018", end_date="2025")
    without_consulting = analyze_long_mission([exp], threshold_months=24)
    assert without_consulting.status != "confirmed"

    with_consulting = analyze_long_mission(
        [exp], threshold_months=24, consulting_status="confirmed"
    )
    assert with_consulting.status == "probable"


# --- identity matching ------------------------------------------------------
def test_identity_name_only_never_strong() -> None:
    m = score_profile_match(
        known_name="Jean Dupont",
        profile_url="https://www.linkedin.com/in/jean-dupont",
        profile_name="Jean Dupont",
    )
    assert m.confidence_level == "ambiguous"


def test_identity_strong_needs_two_corroborations() -> None:
    m = score_profile_match(
        known_name="Jean Dupont",
        known_company="Capgemini",
        known_title="Java Consultant",
        profile_url="https://www.linkedin.com/in/jean-dupont",
        profile_name="Jean Dupont",
        profile_company="Capgemini",
        profile_title="Java Consultant chez Capgemini",
    )
    assert m.confidence_level == "strong"


# --- 41: ranking UNKNOWN != NO ----------------------------------------------
def test_ranking_unknown_beats_confirmed_no() -> None:
    q = CandidateSearchQuery(required_skills=["Java", "Spring Boot"])
    unknown = ExternalCandidateEvidence(
        profile_url="https://www.linkedin.com/in/a",
        matched_skills=["Java", "Spring Boot"],
        long_mission=LongMissionEvidence(status="unknown"),
    )
    negative = ExternalCandidateEvidence(
        profile_url="https://www.linkedin.com/in/b",
        matched_skills=["Java", "Spring Boot"],
        long_mission=LongMissionEvidence(status="no"),
    )
    score_unknown, _ = score_external_candidate(unknown, q)
    score_no, _ = score_external_candidate(negative, q)
    assert score_unknown > score_no


def test_ranking_confirmed_beats_probable_beats_unknown() -> None:
    q = CandidateSearchQuery(required_skills=["Java"])

    def mk(mission: str, consulting: str) -> ExternalCandidateEvidence:
        return ExternalCandidateEvidence(
            profile_url=f"https://www.linkedin.com/in/{mission}-{consulting}",
            matched_skills=["Java"],
            consulting_profile=ConsultingProfileEvidence(status=consulting),
            long_mission=LongMissionEvidence(status=mission),
        )

    confirmed, _ = score_external_candidate(mk("confirmed", "confirmed"), q)
    probable, _ = score_external_candidate(mk("probable", "probable"), q)
    unknown, _ = score_external_candidate(mk("unknown", "unknown"), q)
    assert confirmed > probable > unknown


# --- 42: duplicate people ---------------------------------------------------
def _card(**kw) -> CandidateCard:
    base: dict = {"id": "x"}
    base.update(kw)
    return CandidateCard(**base)


def test_merge_boond_and_linkedin_sharing_url() -> None:
    boond = _card(
        id="123", full_name="Jean Dupont", sources=["boond"], boond_ids=["123"],
        linkedin_url="https://www.linkedin.com/in/jean-dupont",
    )
    linkedin = _card(
        id="li:jean-dupont", full_name="Jean Dupont", sources=["linkedin_web"],
        linkedin_url="https://www.linkedin.com/in/jean-dupont",
        consulting_status="confirmed", long_mission_status="confirmed",
    )
    merged = merge_candidate_cards([boond, linkedin])
    assert len(merged) == 1
    assert set(merged[0].sources) == {"boond", "linkedin_web"}
    assert merged[0].consulting_status == "confirmed"


def test_merge_two_boond_records_same_linkedin_url() -> None:
    a = _card(id="123", sources=["boond"], boond_ids=["123"],
              linkedin_url="https://www.linkedin.com/in/john-doe")
    b = _card(id="456", sources=["boond"], boond_ids=["456"],
              linkedin_url="https://linkedin.com/in/john-doe/")
    merged = merge_candidate_cards([a, b])
    assert len(merged) == 1
    assert set(merged[0].boond_ids) == {"123", "456"}


def test_merge_does_not_merge_homonyms_without_url() -> None:
    a = _card(id="1", full_name="Jean Martin", sources=["boond"], boond_ids=["1"])
    b = _card(id="2", full_name="Jean Martin", sources=["linkedin_web"],
              linkedin_url="https://www.linkedin.com/in/jean-martin-2")
    merged = merge_candidate_cards([a, b])
    assert len(merged) == 2  # same name, no shared URL -> never merged


# --- location preference (francophone / Île-de-France) ----------------------
def _ext(url: str, location: str | None) -> ExternalCandidateEvidence:
    return ExternalCandidateEvidence(
        profile_url=url, matched_skills=["Java"], location=location
    )


def test_idf_request_prefers_local_over_foreign() -> None:
    q = CandidateSearchQuery(required_skills=["Java"], location="Île-de-France")
    paris, _ = score_external_candidate(_ext("https://www.linkedin.com/in/a", "Paris, France"), q)
    bucharest, _ = score_external_candidate(_ext("https://www.linkedin.com/in/b", "Bucharest, Romania"), q)
    assert paris > bucharest


def test_unknown_location_not_penalised_like_foreign() -> None:
    q = CandidateSearchQuery(required_skills=["Java"], location="Île-de-France")
    unknown, _ = score_external_candidate(_ext("https://www.linkedin.com/in/u", None), q)
    foreign, _ = score_external_candidate(_ext("https://www.linkedin.com/in/f", "Bucharest, Romania"), q)
    assert unknown > foreign  # UNKNOWN location is neutral, foreign is demoted


def test_francophone_between_region_and_foreign() -> None:
    q = CandidateSearchQuery(required_skills=["Java"], location="Paris")
    region, bd_r = score_external_candidate(_ext("https://www.linkedin.com/in/r", "Paris, France"), q)
    franco, bd_f = score_external_candidate(_ext("https://www.linkedin.com/in/w", "Bruxelles, Belgique"), q)
    foreign, _ = score_external_candidate(_ext("https://www.linkedin.com/in/x", "Warsaw, Poland"), q)
    assert region >= franco > foreign
    assert bd_r["location"] == "match" and bd_f["location"] == "francophone"


def test_foreign_but_francophone_with_france_experience_not_demoted() -> None:
    # SIJO rule: nationality/current country don't matter as long as the person
    # speaks French AND has had an experience in France. A Bucharest-based dev
    # who speaks French and worked in Paris must outrank a Bucharest dev with
    # neither.
    q = CandidateSearchQuery(required_skills=["Java"], location="Paris")
    ok = ExternalCandidateEvidence(
        profile_url="https://www.linkedin.com/in/ok",
        matched_skills=["Java"],
        location="Bucharest, Romania",
        languages=["French", "English", "Romanian"],
        experiences=[ExternalExperience(title="Consultant", employer="Capgemini",
                                        location="Paris, France", duration_months=20)],
    )
    nope = ExternalCandidateEvidence(
        profile_url="https://www.linkedin.com/in/nope",
        matched_skills=["Java"],
        location="Bucharest, Romania",
        languages=["Romanian", "English"],
        experiences=[ExternalExperience(title="Developer", employer="Local SRL",
                                        location="Bucharest, Romania", duration_months=20)],
    )
    s_ok, bd_ok = score_external_candidate(ok, q)
    s_nope, _ = score_external_candidate(nope, q)
    assert s_ok > s_nope
    assert bd_ok.get("french") is True and bd_ok.get("france_experience") is True
