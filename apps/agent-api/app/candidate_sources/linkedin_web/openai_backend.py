"""OpenAI Responses API web_search backend for LinkedIn discovery.

Isolated from ``source.py`` so the discovery pipeline stays network-free and
unit-testable. Uses the installed OpenAI SDK (>= 2.x): the Responses API with
the built-in ``web_search`` tool and structured outputs via ``responses.parse``.
The cited-source URLs are read from the response's ``url_citation`` annotations
so the source layer can reject any profile URL the search did not actually
surface.

Public web content only — no login, no cookies, no scraping, no browser.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.candidate_sources.linkedin_web.source import BackendResult

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _attr(obj: object, name: str) -> object:
    """Read a field whether ``obj`` is a pydantic-ish object or a dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_cited_urls(response: object) -> list[str]:
    """Collect the URLs the web search actually cited (grounding evidence).

    Robust to the annotation being an object or a dict, and to the message
    content being a list of blocks. Only ``url_citation``-style annotations
    (those carrying a ``url``) are collected — these are the pages the search
    genuinely retrieved, which is what we validate discovered profiles against.
    """
    urls: list[str] = []
    output = getattr(response, "output", None) or []
    for item in output:
        content = _attr(item, "content")
        if not isinstance(content, list):
            continue
        for block in content:
            annotations = _attr(block, "annotations") or []
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                url = _attr(annotation, "url")
                if isinstance(url, str) and url:
                    urls.append(url)
    return urls


class OpenAIWebSearchBackend:
    """Runs one structured web search through the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        linkedin_only: bool = True,
        timeout_seconds: float = 60.0,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - exercised only w/o SDK
            raise RuntimeError(
                "openai package is required for external web search "
                "(pip install openai)"
            ) from exc
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._linkedin_only = linkedin_only

    def _tool_variants(self) -> list[dict[str, object]]:
        """Web-search tool configs to try, most-specific first.

        Different OpenAI API/model versions accept different shapes: the GA
        ``web_search`` type, the older ``web_search_preview``, and the
        ``allowed_domains`` filter is not universally supported. We fall back
        gracefully so a config the account doesn't support doesn't silently
        zero out discovery — the source layer validates the host regardless.
        """
        variants: list[dict[str, object]] = []
        if self._linkedin_only:
            variants.append(
                {"type": "web_search", "filters": {"allowed_domains": ["linkedin.com"]}}
            )
        variants.append({"type": "web_search"})
        variants.append({"type": "web_search_preview"})
        return variants

    async def search(self, prompt: str, schema: type[T]) -> BackendResult:
        from app.candidate_sources.linkedin_web.source import _DISCOVERY_SYSTEM

        messages = [
            {"role": "system", "content": _DISCOVERY_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        last_error: Exception | None = None
        for tool in self._tool_variants():
            try:
                response = await self._client.responses.parse(
                    model=self._model,
                    tools=[tool],
                    input=messages,
                    text_format=schema,
                )
            except Exception as exc:  # noqa: BLE001 — try the next tool shape
                last_error = exc
                logger.info(
                    "linkedin_web.tool_variant_failed",
                    extra={"tool_type": tool.get("type"),
                           "has_filters": "filters" in tool,
                           "error": str(exc)[:300]},
                )
                continue
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = schema()  # empty, valid — degrade to "no profiles"
            return BackendResult(
                parsed=parsed, cited_urls=_extract_cited_urls(response)
            )
        # Every tool shape failed — surface the last error so the source layer
        # logs it (and the search degrades to "no results", not a crash).
        raise RuntimeError(
            f"web_search call failed for all tool variants: {last_error}"
        ) from last_error
