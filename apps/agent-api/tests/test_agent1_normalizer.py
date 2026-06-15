"""Tests for Agent1 candidate data normaliser."""

from __future__ import annotations

import pytest

from app.agents.agent1.normalizer import (
    NORM_EXPERIENCE_SOURCE,
    NORM_EXPERIENCE_YEARS,
    NORM_LANGUAGES,
    NORM_SKILLS,
    NORM_TITLE,
    normalize_candidate,
    normalize_candidates,
)
from app.models.results import SearchResult

# ── helpers ───────────────────────────────────────────────────────────────────

def _result(data: dict | None = None, title: str = "") -> SearchResult:
    return SearchResult(
        id="c1",
        type="consultant",
        title=title,
        snippet="",
        score=0.5,
        source_tool="searchCandidates",
        data=data or {},
    )


# ── experience normalisation ──────────────────────────────────────────────────

class TestNormalizeExperience:
    def test_prefers_cv_years_over_boond_when_higher(self):
        result = _result(
            data={
                "experienceMinYears": 1,
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Développeur Java depuis 2021, 3 ans d'expérience Java",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_falls_back_to_boond_when_cv_missing(self):
        result = _result(data={"experienceMinYears": 5})
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 5
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"

    def test_prefers_tech_doc_years_over_boond(self):
        result = _result(
            data={
                "experienceMinYears": 1,
                "_enrichment_technical_document": {
                    "text": "3 ans d'expérience Java",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "technical_document"

    def test_returns_none_when_no_experience_data(self):
        out = normalize_candidate(_result())
        assert out.data[NORM_EXPERIENCE_YEARS] is None
        assert out.data[NORM_EXPERIENCE_SOURCE] is None

    def test_ignores_implausible_values(self):
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "100 ans d'expérience",  # >50, capped
                },
                "experienceMinYears": 3,
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"


# ── skills normalisation ──────────────────────────────────────────────────────

class TestNormalizeSkills:
    def test_collects_boond_skills(self):
        result = _result(data={"skills": ["Java", "Spring Boot"]})
        out = normalize_candidate(result)
        assert "Java" in out.data[NORM_SKILLS]
        assert "Spring Boot" in out.data[NORM_SKILLS]

    def test_deduplicates_case_insensitive(self):
        result = _result(data={"skills": ["Java", "java", "JAVA"]})
        out = normalize_candidate(result)
        # Only one "Java" variant should remain.
        skills_lower = [s.lower() for s in out.data[NORM_SKILLS]]
        assert skills_lower.count("java") == 1

    def test_supplements_from_cv_when_boond_sparse(self):
        # BoondManager has no skills → CV text should be mined.
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Expertise in Spring Boot, Kafka and Docker",
                },
            }
        )
        out = normalize_candidate(result)
        skills_lower = [s.lower() for s in out.data[NORM_SKILLS]]
        assert any("kafka" in s for s in skills_lower) or any(
            "docker" in s for s in skills_lower
        )

    def test_does_not_mine_cv_when_boond_rich(self):
        # BoondManager already has 5+ skills — CV mining is skipped.
        result = _result(
            data={
                "skills": ["Java", "Spring", "Kafka", "Docker", "K8s"],
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Python expertise",
                },
            }
        )
        out = normalize_candidate(result)
        skills_lower = [s.lower() for s in out.data[NORM_SKILLS]]
        # "python" should NOT appear since CV mining is skipped.
        assert "python" not in skills_lower

    def test_empty_when_no_skill_data(self):
        out = normalize_candidate(_result())
        assert out.data[NORM_SKILLS] == []


# ── language normalisation ────────────────────────────────────────────────────

class TestNormalizeLanguages:
    def test_collects_boond_language_labels(self):
        result = _result(
            data={
                "languages": [
                    {"_languageSpokenLabel": "Anglais", "_languageLevelLabel": "C1"}
                ]
            }
        )
        out = normalize_candidate(result)
        langs = out.data[NORM_LANGUAGES]
        assert any("Anglais" in lang for lang in langs)

    def test_fills_from_cv_when_boond_empty(self):
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Anglais professionnel (C1)",
                },
            }
        )
        out = normalize_candidate(result)
        langs = out.data[NORM_LANGUAGES]
        assert any("Anglais" in lang for lang in langs)

    def test_deduplicates_languages(self):
        result = _result(
            data={
                "languages": [{"_languageSpokenLabel": "Anglais"}],
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "English C1",
                },
            }
        )
        out = normalize_candidate(result)
        anglais_count = sum(1 for l in out.data[NORM_LANGUAGES] if "Anglais" in l)
        assert anglais_count == 1

    def test_empty_when_no_language_data(self):
        out = normalize_candidate(_result())
        assert out.data[NORM_LANGUAGES] == []


# ── title normalisation ───────────────────────────────────────────────────────

class TestNormalizeTitle:
    def test_keeps_existing_title(self):
        result = _result(title="Développeur Java Senior")
        out = normalize_candidate(result)
        assert out.data[NORM_TITLE] == "Développeur Java Senior"

    def test_falls_back_to_detail_title(self):
        result = _result(
            title="",
            data={"_enrichment_detail": {"title": "Lead Architect"}},
        )
        out = normalize_candidate(result)
        assert out.data[NORM_TITLE] == "Lead Architect"

    def test_none_when_no_title(self):
        out = normalize_candidate(_result(title=""))
        assert out.data[NORM_TITLE] is None or out.data[NORM_TITLE] == ""


# ── idempotency ───────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_running_twice_gives_same_result(self):
        result = _result(
            data={
                "skills": ["Java"],
                "experienceMinYears": 3,
                "_enrichment_resume": {"hasContent": True, "extractedText": "5 ans d'expérience"},
            }
        )
        once = normalize_candidate(result)
        twice = normalize_candidate(once)
        assert twice.data[NORM_EXPERIENCE_YEARS] == once.data[NORM_EXPERIENCE_YEARS]
        assert twice.data[NORM_SKILLS] == once.data[NORM_SKILLS]

    def test_original_data_not_mutated(self):
        original_data = {"skills": ["Java"], "experienceMinYears": 3}
        result = _result(data=dict(original_data))
        normalize_candidate(result)
        assert result.data == original_data


# ── batch helper ─────────────────────────────────────────────────────────────

class TestNormalizeCandidates:
    def test_normalises_all_results(self):
        results = [_result(data={"experienceMinYears": i}) for i in range(1, 4)]
        out = normalize_candidates(results)
        assert len(out) == 3
        for i, r in enumerate(out, start=1):
            assert r.data[NORM_EXPERIENCE_YEARS] == i

    def test_handles_empty_list(self):
        assert normalize_candidates([]) == []
