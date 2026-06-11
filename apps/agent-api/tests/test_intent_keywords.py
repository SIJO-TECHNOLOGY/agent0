"""Tests for the deterministic intent keyword heuristics."""

from __future__ import annotations

import pytest

from app.graph.intent_keywords import (
    detect_tools,
    extract_candidate_id,
    extract_keywords,
    extract_min_years_experience,
    _normalize_token,
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


# ---------------------------------------------------------------------------
# Alias / language normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("js", "javascript"),
        ("ts", "typescript"),
        ("k8s", "kubernetes"),
        ("nodejs", "node.js"),
        ("ml", "machine learning"),
        ("ia", "artificial intelligence"),
        ("golang", "go"),
        # lang normalisation (French → English)
        ("developpeur", "developer"),
        ("ingenieur", "engineer"),
        ("securite", "security"),
        # unknown token passes through unchanged
        ("java", "java"),
        ("python", "python"),
    ],
)
def test_normalize_token(token: str, expected: str) -> None:
    assert _normalize_token(token) == expected


def test_extract_keywords_expands_alias() -> None:
    # "JS" should be normalised to "javascript" before deduplication
    keywords = extract_keywords("cherche un développeur JS senior")
    assert "javascript" in keywords
    assert "js" not in keywords


def test_extract_keywords_french_tech_term() -> None:
    # Single-token FR terms are normalised; multi-word phrases are token-split
    # so each token is normalised independently.
    keywords = extract_keywords("expert en intelligence artificielle")
    # "ia" → "artificial intelligence", but "intelligence" and "artificielle"
    # are separate tokens that pass through (no single-token alias for them).
    # The single-token alias "ia" IS resolved:
    keywords_ia = extract_keywords("expert ia python")
    assert "artificial intelligence" in keywords_ia


def test_extract_keywords_lang_normalisation() -> None:
    # "ingenieur" is a type-hint (filtered like "developer") so it won't appear.
    # Other French tech nouns that are NOT type-hints ARE normalised.
    keywords = extract_keywords("expert securite reseaux")
    assert "security" in keywords
    assert "network" in keywords
