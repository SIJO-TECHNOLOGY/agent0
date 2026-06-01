"""Tests for the deterministic intent keyword heuristics."""

from __future__ import annotations

import pytest

from app.graph.intent_keywords import (
    detect_tools,
    extract_candidate_id,
    extract_keywords,
    extract_min_years_experience,
)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Find the candidate information with candidate id 41924", 41924),
        ("candidate id 41924", 41924),
        ("CandidateId=41924", 41924),
        ("candidate_id 41924", 41924),
        ("candidate#41924", 41924),
        # Typo tolerance for a single-letter omission.
        ("Find the cadidate id 41924", 41924),
        ("cadidate id 41924", 41924),
    ],
)
def test_extract_candidate_id_positive(query: str, expected: int) -> None:
    assert extract_candidate_id(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "find senior python consultants",
        "show me projects",
        "candidate 41924",  # missing "id"-style anchor — do not over-trigger
        "id 41924",  # no candidate word — do not over-trigger
        "",
    ],
)
def test_extract_candidate_id_negative(query: str) -> None:
    assert extract_candidate_id(query) is None


@pytest.mark.parametrize(
    "query,expected",
    [
        ("more than 10 years experience on java", 10),
        ("5+ years of experience", 5),
        ("at least 7 yrs experience", 7),
        ("3 year experience", 3),
    ],
)
def test_extract_min_years_experience_positive(query: str, expected: int) -> None:
    assert extract_min_years_experience(query) == expected


def test_extract_min_years_experience_returns_minimum_when_multiple_present() -> None:
    # Two explicit "<N> years" phrases — extractor returns the smaller of
    # the two so we never over-claim the required experience filter.
    assert extract_min_years_experience("at least 5 years up to 10 years") == 5


@pytest.mark.parametrize(
    "query",
    [
        "find senior python consultants",
        "candidate id 41924",
        "",
    ],
)
def test_extract_min_years_experience_negative(query: str) -> None:
    assert extract_min_years_experience(query) is None


def test_extract_keywords_filters_noise_in_long_candidate_search() -> None:
    query = (
        "search a dev who has more 10 years experience on java and his last "
        "experience should be in CIB"
    )
    keywords = extract_keywords(query)
    # The planner should distil this down to the real domain terms.
    assert "java" in keywords
    assert "cib" in keywords
    # Common verbs, modals, pronouns, and "years/experience" must be filtered.
    noise = {
        "search",
        "dev",
        "who",
        "has",
        "more",
        "years",
        "experience",
        "his",
        "last",
        "should",
        "be",
    }
    assert not (noise & set(keywords))


def test_extract_keywords_filters_french_request_noise() -> None:
    assert extract_keywords("trouve moi des profils java") == ["java"]


def test_detect_tools_accepts_accented_french_consultant_hint() -> None:
    assert "search_consultants" in detect_tools("cherche un développeur java")


def test_detect_tools_picks_consultant_hint_for_dev() -> None:
    assert "search_consultants" in detect_tools("search a dev with java")
