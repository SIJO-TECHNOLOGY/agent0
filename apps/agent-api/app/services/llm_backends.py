"""Concrete ``ChatFn`` backends for the LLM planner.

Each backend is built lazily inside ``build_chat_fn`` so importing this
module does not require any LLM SDK to be installed. Tests that use a
fake ``ChatFn`` never reach this code.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.services.llm_planner import ChatFn

logger = logging.getLogger(__name__)


class LlmBackendError(RuntimeError):
    """Raised when the requested LLM backend cannot be initialized."""


def build_chat_fn(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    temperature: float,
) -> ChatFn:
    """Construct a ``ChatFn`` for the named provider.

    Currently only ``anthropic`` is supported. Failure modes:
    - unknown provider → ``LlmBackendError``
    - missing api_key → ``LlmBackendError``
    - SDK not installed → ``LlmBackendError``
    """
    if not api_key:
        raise LlmBackendError(
            f"LLM provider {provider!r} requires an API key but none was provided."
        )

    normalized = provider.strip().lower()
    if normalized == "anthropic":
        return _build_anthropic_chat_fn(
            model=model, api_key=api_key, temperature=temperature
        )
    if normalized == "openai":
        return _build_openai_chat_fn(
            model=model, api_key=api_key, temperature=temperature
        )

    raise LlmBackendError(f"Unknown LLM provider {provider!r}.")


def _build_anthropic_chat_fn(
    *, model: str, api_key: str, temperature: float
) -> ChatFn:
    try:
        from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — exercised only when SDK missing
        raise LlmBackendError(
            "anthropic SDK is not installed; either install it or set "
            "USE_LLM_PLANNER=false."
        ) from exc

    client = AsyncAnthropic(api_key=api_key)

    async def chat_fn(system_prompt: str, user_prompt: str) -> str:
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Concatenate any text blocks returned by the API.
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        if not parts:
            raise LlmBackendError(
                "Anthropic response contained no text content."
            )
        return "".join(parts)

    return chat_fn


def _build_openai_chat_fn(
    *, model: str, api_key: str, temperature: float
) -> ChatFn:
    try:
        from openai import AsyncOpenAI  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — exercised only when SDK missing
        raise LlmBackendError(
            "openai SDK is not installed; either install it or set "
            "USE_LLM_PLANNER=false."
        ) from exc

    client = AsyncOpenAI(api_key=api_key)

    async def chat_fn(system_prompt: str, user_prompt: str) -> str:
        response = await client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
            temperature=temperature,
        )
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise LlmBackendError(
                "OpenAI response contained no output_text."
            )
        return text

    return chat_fn
