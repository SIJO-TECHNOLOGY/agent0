"""Tests for the LLM backend factory."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.services.llm_backends import LlmBackendError, build_chat_fn


def test_build_chat_fn_raises_when_api_key_missing() -> None:
    with pytest.raises(LlmBackendError):
        build_chat_fn(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key=None,
            temperature=0.0,
        )


def test_build_chat_fn_raises_when_api_key_missing_openai() -> None:
    with pytest.raises(LlmBackendError):
        build_chat_fn(
            provider="openai",
            model="gpt-5.2",
            api_key=None,
            temperature=0.0,
        )


def test_build_chat_fn_raises_on_unknown_provider() -> None:
    with pytest.raises(LlmBackendError):
        build_chat_fn(
            provider="random-llm",
            model="some-model",
            api_key="sk-fake",
            temperature=0.0,
        )


def test_build_chat_fn_returns_callable_when_anthropic_sdk_present() -> None:
    # The SDK is in pyproject; if it's installed in the env we should get
    # a callable back. If for some reason it isn't, skip rather than fail.
    try:
        chat_fn = build_chat_fn(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="sk-fake-only-for-init",
            temperature=0.0,
        )
    except LlmBackendError as exc:
        pytest.skip(f"anthropic SDK not available in env: {exc}")
    assert callable(chat_fn)


# ---------------------------------------------------------------------------
# OpenAI backend (uses a fake `openai` module so no real SDK / network)
# ---------------------------------------------------------------------------


class _StubResponse:
    """Mirror the shape of openai.responses.create() return value."""

    def __init__(self, output_text: str | None) -> None:
        self.output_text = output_text


class _StubResponses:
    def __init__(self, *, output_text: str | None) -> None:
        self._output_text = output_text
        self.last_call_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _StubResponse:
        self.last_call_kwargs = kwargs
        return _StubResponse(self._output_text)


class _StubAsyncOpenAI:
    instances: list["_StubAsyncOpenAI"] = []

    def __init__(self, *, api_key: str, output_text: str | None = "hi") -> None:
        self.api_key = api_key
        self.responses = _StubResponses(output_text=output_text)
        _StubAsyncOpenAI.instances.append(self)


def _install_stub_openai(
    monkeypatch: pytest.MonkeyPatch, *, output_text: str | None = "hi"
) -> type[_StubAsyncOpenAI]:
    """Inject a fake `openai` module so build_chat_fn's lazy import lands on it."""

    _StubAsyncOpenAI.instances.clear()

    def _factory(*, api_key: str) -> _StubAsyncOpenAI:
        return _StubAsyncOpenAI(api_key=api_key, output_text=output_text)

    module = types.ModuleType("openai")
    module.AsyncOpenAI = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return _StubAsyncOpenAI


@pytest.mark.asyncio
async def test_openai_backend_uses_responses_api_with_planner_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_openai(monkeypatch, output_text='{"plan": []}')

    chat_fn = build_chat_fn(
        provider="openai",
        model="gpt-5.2",
        api_key="sk-fake",
        temperature=0.3,
    )
    assert callable(chat_fn)

    text = await chat_fn("SYSTEM-PROMPT", "USER-PROMPT")
    assert text == '{"plan": []}'

    assert len(_StubAsyncOpenAI.instances) == 1
    client = _StubAsyncOpenAI.instances[0]
    assert client.api_key == "sk-fake"
    assert client.responses.last_call_kwargs == {
        "model": "gpt-5.2",
        "instructions": "SYSTEM-PROMPT",
        "input": "USER-PROMPT",
        "temperature": 0.3,
    }


@pytest.mark.asyncio
async def test_openai_backend_raises_when_output_text_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_openai(monkeypatch, output_text=None)
    chat_fn = build_chat_fn(
        provider="openai",
        model="gpt-5.2",
        api_key="sk-fake",
        temperature=0.0,
    )
    with pytest.raises(LlmBackendError):
        await chat_fn("sys", "user")


@pytest.mark.asyncio
async def test_openai_backend_raises_when_output_text_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_openai(monkeypatch, output_text="   ")
    chat_fn = build_chat_fn(
        provider="openai",
        model="gpt-5.2",
        api_key="sk-fake",
        temperature=0.0,
    )
    with pytest.raises(LlmBackendError):
        await chat_fn("sys", "user")


def test_openai_backend_raises_when_sdk_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate "openai not installed" by replacing the module entry with
    # one that has no AsyncOpenAI attribute, then forcing reimport via
    # blocking the real module.
    blocked = types.ModuleType("openai")
    # Removing AsyncOpenAI means the `from openai import AsyncOpenAI`
    # inside the backend will raise ImportError.
    monkeypatch.setitem(sys.modules, "openai", blocked)

    with pytest.raises(LlmBackendError):
        build_chat_fn(
            provider="openai",
            model="gpt-5.2",
            api_key="sk-fake",
            temperature=0.0,
        )
