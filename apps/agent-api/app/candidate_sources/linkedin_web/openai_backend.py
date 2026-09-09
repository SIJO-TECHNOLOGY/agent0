"""OpenAI Responses API web_search backend for LinkedIn discovery.

Isolated from ``source.py`` so the discovery pipeline stays network-free and
unit-testable. Uses the installed OpenAI SDK (>= 2.x) Responses API in TWO
steps: (1) ``responses.create`` with the built-in ``web_search`` tool, whose
``url_citation`` annotations are the REAL pages the search retrieved (our
grounding evidence); (2) ``responses.parse`` (no tool) to structure ONLY those
cited profiles. Structured-output mode is never used WITH web_search because it
suppresses citations and lets the model fabricate profiles.

Public web content only — no login, no cookies, no scraping, no browser.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.candidate_sources.linkedin_web.source import BackendResult
from app.candidate_sources.linkedin_web.url_utils import (
    canonical_profile_url,
    is_profile_url,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# System prompt for the second (structuring) pass — no web tool, so it must
# only reformat the findings and never introduce a new URL.
_STRUCTURE_SYSTEM = (
    "You convert web-search findings about people into structured LinkedIn "
    "member profiles. Use ONLY the profile URLs given to you, verbatim. Use "
    "null for any field not present in the findings; never invent values. "
    "Distinguish EMPLOYER (who paid the person) from CLIENT (the end customer "
    "of a mission): set explicit_client_mission=true only when a client is "
    "clearly named for that line. Set consulting_context=true for an ESN / "
    "consulting / freelance engagement."
)


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

    # Tool-type variants to try (no domain filter: `allowed_domains` is not
    # supported by all models, e.g. gpt-4o-mini returns HTTP 400, and the
    # prompt + host validation + grounding already constrain to LinkedIn).
    _TOOL_TYPES: tuple[str, ...] = ("web_search", "web_search_preview")

    async def _web_search(self, prompt: str):
        """Run one grounded web search (text mode) and return the response.

        Text mode (`responses.create`) is deliberate: it attaches real
        ``url_citation`` annotations — the actual pages the search retrieved —
        which is our grounding evidence. Structured-output mode suppresses
        those citations and lets the model fabricate, so it is NOT used here.
        """
        from app.candidate_sources.linkedin_web.source import _DISCOVERY_SYSTEM

        last_error: Exception | None = None
        for tool_type in self._TOOL_TYPES:
            try:
                return await self._client.responses.create(
                    model=self._model,
                    tools=[{"type": tool_type}],
                    input=[
                        {"role": "system", "content": _DISCOVERY_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                )
            except Exception as exc:  # noqa: BLE001 — try the next tool shape
                last_error = exc
                logger.info(
                    "linkedin_web.tool_variant_failed",
                    extra={"tool_type": tool_type, "error": str(exc)[:300]},
                )
                continue
        raise RuntimeError(
            f"web_search call failed for all tool types: {last_error}"
        ) from last_error

    async def search(self, prompt: str, schema: type[T]) -> BackendResult:
        # Step 1 — grounded web search (text) → the REAL URLs the search cited.
        response = await self._web_search(prompt)
        cited_urls = _extract_cited_urls(response)
        text = getattr(response, "output_text", "") or ""

        profile_citations = [
            url for url in cited_urls if is_profile_url(url)
        ]
        # No real LinkedIn profile was cited → return nothing (never fabricate).
        if not profile_citations:
            return BackendResult(parsed=schema(), cited_urls=cited_urls)

        # Step 2 — structure ONLY the cited profiles (no web tool, so no new
        # ungrounded URLs can appear). The model formats the findings; every
        # profile_url must be one the search actually cited.
        canonical = []
        seen: set[str] = set()
        for url in profile_citations:
            canon = canonical_profile_url(url) or url
            if canon not in seen:
                seen.add(canon)
                canonical.append(canon)
        struct_prompt = (
            "Structure the following web-search findings into LinkedIn member "
            "profiles. Use ONLY these profile URLs, one entry per URL, verbatim "
            "(do not invent any other URL):\n" + "\n".join(canonical)
            + "\n\nFindings:\n" + text[:12000]
        )
        try:
            structured = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": _STRUCTURE_SYSTEM},
                    {"role": "user", "content": struct_prompt},
                ],
                text_format=schema,
            )
            parsed = getattr(structured, "output_parsed", None) or schema()
        except Exception as exc:  # noqa: BLE001 — structuring is best-effort
            logger.info("linkedin_web.structure_failed", extra={"error": str(exc)[:300]})
            parsed = schema()
        # Grounding set = the real cited URLs (canonical form included).
        return BackendResult(parsed=parsed, cited_urls=cited_urls + canonical)
