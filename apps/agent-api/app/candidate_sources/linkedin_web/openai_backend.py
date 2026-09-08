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


def _extract_cited_urls(response: object) -> list[str]:
    """Collect url_citation annotation URLs from a Responses API response."""
    urls: list[str] = []
    output = getattr(response, "output", None) or []
    for item in output:
        for content in getattr(item, "content", None) or []:
            for annotation in getattr(content, "annotations", None) or []:
                url = getattr(annotation, "url", None)
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

    def _web_search_tool(self) -> dict[str, object]:
        tool: dict[str, object] = {"type": "web_search"}
        if self._linkedin_only:
            # Domain-restrict to LinkedIn where the API supports it. Harmless
            # extra hint otherwise; the source layer also validates the host.
            tool["filters"] = {"allowed_domains": ["linkedin.com"]}
        return tool

    async def search(self, prompt: str, schema: type[T]) -> BackendResult:
        from app.candidate_sources.linkedin_web.source import _DISCOVERY_SYSTEM

        response = await self._client.responses.parse(
            model=self._model,
            tools=[self._web_search_tool()],
            input=[
                {"role": "system", "content": _DISCOVERY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            text_format=schema,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            parsed = schema()  # empty, valid — degrade to "no profiles"
        return BackendResult(parsed=parsed, cited_urls=_extract_cited_urls(response))
