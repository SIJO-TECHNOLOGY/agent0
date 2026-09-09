"""Tests for external-source construction / API-key resolution."""

from __future__ import annotations

from types import SimpleNamespace

from app.candidate_sources.factory import CachedExternalSource, build_external_source


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        external_search_enabled=True,
        external_search_provider="openai_web",
        external_search_model="gpt-4o-mini",
        external_search_linkedin_only=True,
        external_search_max_queries=5,
        external_search_max_results=20,
        external_search_cache_ttl_seconds=0.0,
        external_search_api_key=None,
        openai_api_key=None,
        llm_provider="openai",
        llm_api_key=None,
        llm_timeout_seconds=60.0,
        candidate_long_mission_threshold_months=24,
        candidate_prefer_consulting_profile=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_disabled_returns_none() -> None:
    assert build_external_source(_settings(external_search_enabled=False)) is None


def test_unknown_provider_returns_none() -> None:
    assert build_external_source(_settings(external_search_provider="serpapi")) is None


def test_no_key_returns_none() -> None:
    assert build_external_source(_settings()) is None


def test_dedicated_external_key_used() -> None:
    assert isinstance(
        build_external_source(_settings(external_search_api_key="sk-ext")),
        CachedExternalSource,
    )


def test_openai_key_used() -> None:
    assert isinstance(
        build_external_source(_settings(openai_api_key="sk-openai")),
        CachedExternalSource,
    )


def test_falls_back_to_llm_api_key_when_provider_openai() -> None:
    # A project that only sets LLM_API_KEY (provider=openai) still powers
    # web search without duplicating the key.
    assert isinstance(
        build_external_source(_settings(llm_provider="openai", llm_api_key="sk-llm")),
        CachedExternalSource,
    )


def test_no_fallback_to_llm_key_when_provider_not_openai() -> None:
    # An Anthropic LLM key must NOT be used for OpenAI web search.
    assert build_external_source(
        _settings(llm_provider="anthropic", llm_api_key="sk-ant-xxx")
    ) is None
