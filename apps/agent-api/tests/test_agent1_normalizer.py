"""Tests for Agent1 candidate data normaliser."""

from __future__ import annotations

import pytest

from datetime import date

from app.agents.agent1.normalizer import (
    NORM_EXPERIENCE_SOURCE,
    NORM_EXPERIENCE_YEARS,
    NORM_LANGUAGES,
    NORM_SKILLS,
    NORM_TITLE,
    _estimate_years_from_graduation,
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
    def test_structured_boond_years_are_authoritative(self):
        # BoondManager's structured experienceMinYears is curated and wins over
        # any free-text mention (avoids inflated values mined from CV prose).
        result = _result(
            data={
                "experienceMinYears": 16,
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "40 ans. Société fondée il y a 40 ans.",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 16
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"

    def test_clear_cv_statement_overrides_structured_level(self):
        # Policy: a years figure CLEARLY stated in the CV ("X years of
        # experience") wins over the structured level band.
        result = _result(
            data={
                "_experienceLabel": "10 à 15 ans",
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "12 years of experience in software.",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 12
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_unclear_cv_number_keeps_structured_level(self):
        # An age / incidental number in the CV is NOT a clear experience
        # statement, so the structured level band is shown instead (no number).
        result = _result(
            data={
                "_experienceLabel": "10 à 15 ans",
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "40 ans. Société fondée il y a 40 ans.",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] is None
        assert out.data[NORM_EXPERIENCE_SOURCE] is None

    def test_uses_cv_years_when_boond_missing(self):
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Développeur Java depuis 2021, 3 ans d'expérience Java",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_cv_age_does_not_shadow_experience_line(self):
        # Real failing case: the CV states the candidate's age ("40 ans") on
        # one line and his experience ("16 ans d'expérience") on another. The
        # age must never be read as experience — Agent1 must pick 16, not 40,
        # even when PDF extraction collapses the lines onto one.
        for cv_text in (
            "40 ans 16 ans d'expérience",
            "40 ans. 16 ans d'expérience en finance.",
            "Âge: 40 ans   Expérience: 16 ans",
            "16 ans d'expérience 40 ans",
        ):
            result = _result(
                data={"_enrichment_resume": {"hasContent": True, "extractedText": cv_text}}
            )
            out = normalize_candidate(result)
            assert out.data[NORM_EXPERIENCE_YEARS] == 16, cv_text
            assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_falls_back_to_boond_when_cv_missing(self):
        result = _result(data={"experienceMinYears": 5})
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 5
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"

    def test_uses_tech_doc_years_when_boond_missing(self):
        result = _result(
            data={
                "_enrichment_technical_document": {
                    "text": "3 ans d'expérience Java",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "technical_document"

    def test_ignores_unqualified_year_mentions(self):
        # Numbers not tied to an experience keyword must be ignored, so a CV
        # that says "40 ans" (age) or "4 years of data" never inflates XP.
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": (
                        "40 ans. Analyzed 4 years of data. "
                        "5 ans d'expérience en finance."
                    ),
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 5
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_extracts_years_from_techdoc_summary(self):
        # "3+ years of hands-on technical experience" lives in the summary field.
        result = _result(
            data={
                "_enrichment_technical_document": {
                    "summary": "Senior Data Engineer with 3+ years of hands-on technical experience building production level solutions.",
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


class TestGraduationEstimate:
    def test_estimate_from_diploma_range_end_year(self):
        # "2017-2020" → end year 2020; estimate = current_year - 2020.
        data = {
            "_enrichment_technical_document": {
                "diplomas": ["Master MEng - ENSEEIHT 2017-2020"],
            }
        }
        assert _estimate_years_from_graduation(data, current_year=2026) == 6

    def test_estimate_takes_latest_graduation(self):
        data = {
            "_enrichment_resume": {
                "hasContent": True,
                "extractedText": (
                    "FORMATION\n"
                    "Licence informatique 2014\n"
                    "Master data science 2016\n"
                ),
            }
        }
        # Latest end year is 2016 → 2026 - 2016 = 10.
        assert _estimate_years_from_graduation(data, current_year=2026) == 10

    def test_no_graduation_year_returns_none(self):
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": "no dates here"}}
        assert _estimate_years_from_graduation(data, current_year=2026) is None

    def test_conflict_without_explicit_cv_uses_graduation(self):
        # Structured says 4 years, but the CV shows an age (conflict) and a
        # graduation year → Agent1 estimates from the diploma instead.
        result = _result(
            data={
                "experienceMinYears": 4,
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "45 ans. Master en informatique 2010.",
                },
            }
        )
        out = normalize_candidate(result)
        expected = date.today().year - 2010
        assert out.data[NORM_EXPERIENCE_YEARS] == expected
        assert out.data[NORM_EXPERIENCE_SOURCE] == "graduation"

    def test_explicit_cv_figure_blocks_graduation_estimate(self):
        # An explicit CV experience figure wins; graduation is not used.
        result = _result(
            data={
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "40 ans. 12 years of experience. Master 2010.",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 12
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv"

    def test_no_conflict_does_not_trigger_graduation(self):
        # A graduation year alone (no conflict) does not override; the rule is
        # "conflict AND no explicit figure".
        result = _result(
            data={
                "experienceMinYears": 5,
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Master en informatique 2010.",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 5
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

    def test_pattern_skills_extracted_from_cv_even_when_boond_rich(self):
        # Known tech skills (via KNOWN_SKILL_PATTERNS) are always extracted from
        # the CV, even when BoondManager already provides rich structured data.
        # This ensures skills mentioned in free-text prose surface in the card.
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
        # Python is a known pattern → should be extracted from CV text.
        assert "python" in skills_lower
        # Boond structured skills must still be present.
        assert "java" in skills_lower

    def test_heuristic_tokens_not_extracted_when_boond_rich(self):
        # Heuristic free-text mining (capitalised tokens) is suppressed when
        # boond already provides 3+ skills — only pattern-based labels appear.
        result = _result(
            data={
                "skills": ["Java", "Spring", "Kafka"],
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Expert in Zephyr methodology and Blorq frameworks",
                },
            }
        )
        out = normalize_candidate(result)
        skills_lower = [s.lower() for s in out.data[NORM_SKILLS]]
        # "Zephyr" and "Blorq" are not in KNOWN_SKILL_PATTERNS → not extracted.
        assert "zephyr" not in skills_lower
        assert "blorq" not in skills_lower

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
