"""Tests for Agent1 candidate data normaliser."""

from __future__ import annotations

import pytest

from datetime import date

from app.agents.agent1.normalizer import (
    NORM_CONFLICTS,
    NORM_EXPERIENCE_SOURCE,
    NORM_EXPERIENCE_YEARS,
    NORM_LANGUAGES,
    NORM_SKILLS,
    NORM_TITLE,
    _estimate_years_from_graduation,
    _sum_experience_durations,
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

    def test_uses_experience_level_when_cv_unclear(self):
        # An age / incidental number in the CV is NOT a clear experience figure,
        # so the recruiter-set experience level ("10 à 15 ans" → 10) is used.
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
        assert out.data[NORM_EXPERIENCE_YEARS] == 10
        assert out.data[NORM_EXPERIENCE_SOURCE] == "experience_level"

    def test_experience_level_parsed_from_label(self):
        out = normalize_candidate(_result(data={"_experienceLabel": "3 ans"}))
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "experience_level"

    def test_experience_level_pas_dexperience_is_zero(self):
        out = normalize_candidate(_result(data={"_experienceLabel": "Pas d'expérience"}))
        assert out.data[NORM_EXPERIENCE_YEARS] == 0
        assert out.data[NORM_EXPERIENCE_SOURCE] == "experience_level"

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

    def test_structured_diplomas_count_all_years_no_keyword_needed(self):
        # The tech-doc `diplomas` field IS a list of diplomas, so every year
        # counts — even when the diploma type ("Maitrise") isn't a known keyword.
        # The latest degree (2008) wins over the baccalauréat (2004).
        data = {
            "_enrichment_technical_document": {
                "diplomas": [
                    "2008 - Maitrise - informatique de gestion, FSEGN",
                    "2004 - Baccalauréat - Mathématiques",
                ],
            }
        }
        assert _estimate_years_from_graduation(data, current_year=2026) == 18

    def test_continuing_education_diploma_does_not_reset_career_start(self):
        # The Raja case: BAC 2003, engineering degree 2009, then a CNAM Master
        # in 2022 obtained mid-career (formation continue). The career starts
        # at the end of the INITIAL education block (2009 — the 2003→2009 gap
        # is a normal BAC→ingénieur chain), NOT at the 2022 degree, which
        # would absurdly yield 4 years for a ~17-year profile.
        data = {
            "_enrichment_technical_document": {
                "diplomas": [
                    "2022 - Master 2 finance de marché - CNAM",
                    "2009 - Diplôme national d'ingénieur informatique - INSAT",
                    "2003 - BAC Math - Lycée Pilote Ariana",
                ],
            }
        }
        assert _estimate_years_from_graduation(data, current_year=2026) == 17

    def test_cv_freetext_ignores_job_years_near_no_diploma_kw(self):
        # A job start year not next to a diploma keyword must not be taken; only
        # the diploma date is used.
        data = {
            "_enrichment_resume": {
                "hasContent": True,
                "extractedText": (
                    "Master informatique 2013\n"
                    "EXPERIENCE\n"
                    "Developpeur JAVA 2018 - 2021 chez Amundi\n"
                ),
            }
        }
        # Graduation = 2013 (master), not 2021 (current job).
        assert _estimate_years_from_graduation(data, current_year=2026) == 13

    def test_job_title_engineer_not_taken_as_graduation(self):
        # "Ingénieur" as a JOB TITLE (LinkedIn-style) must not make its job year
        # a graduation year.
        data = {
            "_enrichment_resume": {
                "hasContent": True,
                "extractedText": "Ingénieur JAVA/JEE février 2019 - juin 2019\n",
            }
        }
        assert _estimate_years_from_graduation(data, current_year=2026) is None

    def test_no_graduation_year_returns_none(self):
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": "no dates here"}}
        assert _estimate_years_from_graduation(data, current_year=2026) is None

    def test_curated_value_kept_but_conflict_flagged(self):
        # Structured says 4 years; the CV shows an age and a graduation year.
        # The curated value is KEPT (not overridden) and the conflict is flagged
        # so the LLM reconciler can arbitrate.
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
        assert out.data[NORM_EXPERIENCE_YEARS] == 4
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"
        assert out.data[NORM_CONFLICTS]  # non-empty (age and/or graduation gap)

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

    def test_no_experience_anywhere_uses_graduation_without_conflict(self):
        # No experience figure anywhere, no structured level → estimate from the
        # graduation year even though there is no conflict.
        result = _result(
            data={
                "_enrichment_technical_document": {
                    "diplomas": ["Master informatique - ENSEEIHT 2015"],
                },
            }
        )
        out = normalize_candidate(result)
        expected = date.today().year - 2015
        assert out.data[NORM_EXPERIENCE_YEARS] == expected
        assert out.data[NORM_EXPERIENCE_SOURCE] == "graduation"

    def test_experience_level_preferred_over_graduation(self):
        # The recruiter-set experience level is curated → used as-is, NOT
        # overridden by a graduation estimate (the conflict is only flagged).
        result = _result(
            data={
                "_experienceLabel": "10 à 15 ans",
                "_enrichment_technical_document": {
                    "diplomas": ["Master informatique 2015"],
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 10
        assert out.data[NORM_EXPERIENCE_SOURCE] == "experience_level"

    def test_graduation_disagreement_flags_but_keeps_curated_source(self):
        # Structured says 5 years; the diploma implies far more → the curated
        # value is KEPT (not overridden) and the disagreement is flagged for the
        # LLM reconciler to arbitrate using the full CV.
        grad_year = 2010
        result = _result(
            data={
                "experienceMinYears": 5,
                "_enrichment_technical_document": {
                    "diplomas": [f"Master informatique {grad_year}"],
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 5
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"
        assert "experience_vs_graduation_disagreement" in out.data[NORM_CONFLICTS]

    def test_sum_experience_durations_from_cv(self):
        cv = (
            "Dev senior juillet 2019 - Present (4 ans 10 mois)\n"
            "Consultant décembre 2016 - janvier 2019 (2 ans 2 mois)\n"
            "Stage 2015 - 2015 (moins d'un an)\n"
        )
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        # 58 + 26 + 6 months = 90 → round(90/12) = 8 (note: 7.5 rounds to 8).
        assert _sum_experience_durations(data) == 8

    def test_sum_durations_none_when_absent(self):
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": "no durations"}}
        assert _sum_experience_durations(data) is None

    def test_sum_durations_from_date_ranges(self):
        # No parenthesised durations — the work-history date ranges themselves
        # are summed: juil 2019→(mai 2026) = 82 mois + déc 2016→janv 2019 = 25
        # mois → 107 mois → 9 ans.
        cv = (
            "EXPERIENCES\n"
            "Dev senior chez Acme juillet 2019 - aujourd'hui\n"
            "Consultant chez Beta décembre 2016 - janvier 2019\n"
        )
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) == 9

    def test_sum_durations_bare_year_ranges(self):
        # "2018 - 2021" without months → plain year difference (3 ans).
        cv = "Développeur JAVA 2018 - 2021 chez Amundi\n"
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) == 3

    def test_sum_durations_merges_overlapping_ranges(self):
        # Parallel roles must not double-count: 2015-2020 and 2018-2021 merge
        # into 2015-2021 → 6 ans (not 9).
        cv = (
            "Lead dev 2015 - 2020 chez Acme\n"
            "Freelance 2018 - 2021 pour Beta\n"
        )
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) == 6

    def test_sum_durations_ignores_education_ranges(self):
        # A date range next to a diploma keyword is education, not work.
        cv = "FORMATION\nMaster informatique 2010 à 2013 - Université de Lyon\n"
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) is None

    def test_parenthesised_durations_win_over_date_ranges(self):
        # When the CV states its own arithmetic, trust it — don't also add the
        # date ranges (that would double-count the same roles).
        cv = "Dev juillet 2019 - aujourd'hui (2 ans 1 mois, temps partiel)\n"
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) == 2

    def test_numeric_month_ranges(self):
        # "07/2019 - 01/2021" → 18 mois → 2 ans (arrondi).
        cv = "Ingénieur d'études 07/2019 - 01/2021 chez Gamma\n"
        data = {"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        assert _sum_experience_durations(data, today=date(2026, 5, 1)) == 2

    def test_duration_sum_overrides_structured_and_flags_disagreement(self):
        # Structured says 20 years but the CV durations sum to ~3 → the CV
        # (2nd priority, right after an explicit statement) wins, and the
        # disagreement with the structured field is flagged for LLM review.
        result = _result(
            data={
                "experienceMinYears": 20,
                "_enrichment_resume": {
                    "hasContent": True,
                    "extractedText": "Dev 2021 - Present (3 ans)\n",
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv_durations"
        assert "experience_vs_structured_disagreement" in out.data[NORM_CONFLICTS]
        assert "experience_estimated_from_durations" in out.data[NORM_CONFLICTS]

    def test_duration_sum_fills_gap_when_no_other_source(self):
        # No explicit statement, no structured years, no label, no diploma —
        # the CV's per-role durations are the only signal and must fill the
        # card instead of "not specified". Flagged for LLM review.
        cv = (
            "Dev senior juillet 2019 - Present (4 ans 10 mois)\n"
            "Consultant décembre 2016 - janvier 2019 (2 ans 2 mois)\n"
        )
        result = _result(
            data={"_enrichment_resume": {"hasContent": True, "extractedText": cv}}
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 7
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv_durations"
        assert "experience_estimated_from_durations" in out.data[NORM_CONFLICTS]

    def test_duration_sum_preferred_over_graduation_estimate(self):
        # Both estimates available → durations (time actually worked) win over
        # the graduation year (which assumes continuous work).
        cv = "Dev 2021 - Present (3 ans)\n"
        result = _result(
            data={
                "_enrichment_resume": {"hasContent": True, "extractedText": cv},
                "_enrichment_technical_document": {
                    "diplomas": ["Master informatique 2010"],
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 3
        assert out.data[NORM_EXPERIENCE_SOURCE] == "cv_durations"

    def test_zero_years_is_a_genuine_value(self):
        # "Pas d'expérience" resolves to experienceMinYears=0 on the MCP side;
        # it must surface as 0, not as "not specified".
        result = _result(data={"experienceMinYears": 0})
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == 0
        assert out.data[NORM_EXPERIENCE_SOURCE] == "boondmanager"

    def test_graduation_agreement_keeps_structured(self):
        # When the graduation estimate agrees with the structured value (within
        # the margin), there is no conflict and the structured value is kept.
        grad_year = 2010
        structured = date.today().year - grad_year  # exact match → no disagreement
        result = _result(
            data={
                "experienceMinYears": structured,
                "_enrichment_technical_document": {
                    "diplomas": [f"Master informatique {grad_year}"],
                },
            }
        )
        out = normalize_candidate(result)
        assert out.data[NORM_EXPERIENCE_YEARS] == structured
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
