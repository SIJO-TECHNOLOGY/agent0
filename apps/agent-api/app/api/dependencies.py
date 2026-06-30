"""Shared FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.mcp.client import McpClient
from app.services.search_service import SearchService


class McpClientUnavailableError(RuntimeError):
    """Raised when no MCP client has been bound to `app.state.mcp_client`.

    Translated to HTTP 503 with the standard error envelope by the
    handler registered in `app.main`. Fail-fast: never fall back to
    a mock client at request time.
    """


def get_mcp_client(request: Request) -> McpClient:
    """Return the MCP client bound to the FastAPI app.

    The client is bound during the FastAPI lifespan startup by
    `app.mcp.factory.create_mcp_client`. Tests may override
    `app.state.mcp_client` directly. There is intentionally no
    fallback: a missing client is a startup-or-config failure, not
    a runtime fallback to fake data.
    """
    client = getattr(request.app.state, "mcp_client", None)
    if client is None:
        raise McpClientUnavailableError(
            "app.state.mcp_client is not set; lifespan startup may have "
            "failed or been bypassed."
        )
    return client


def get_search_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    mcp_client: McpClient = Depends(get_mcp_client),
) -> SearchService:
    override = getattr(request.app.state, "search_service", None)
    if isinstance(override, SearchService):
        return override
    llm_planner = getattr(request.app.state, "llm_planner", None)
    semantic_scorer = None
    if settings.enable_semantic_scoring and settings.openai_api_key:
        from app.services.semantic_scorer import get_semantic_scorer
        semantic_scorer = get_semantic_scorer(
            api_key=settings.openai_api_key,
            model=settings.semantic_model,
        )
    agent1_reconciler = _build_agent1_reconciler(settings)
    return SearchService(
        mcp_client=mcp_client,
        max_replan_attempts=settings.max_replan_attempts,
        mcp_max_retries=settings.mcp_max_retries,
        llm_planner=llm_planner,
        max_plan_steps=settings.llm_max_plan_steps,
        use_llm_replan=settings.use_llm_replan,
        replan_skip_score=settings.replan_skip_score,
        agent_trace=settings.agent_trace != "off",
        agent_trace_verbose=settings.agent_trace == "verbose",
        semantic_scorer=semantic_scorer,
        semantic_boost_weight=settings.semantic_boost_weight,
        agent1_reconciler=agent1_reconciler,
        allow_clarification=settings.allow_clarification,
    )


def _build_agent1_reconciler(settings: Settings):
    """Build the Agent1 LLM reconciler when enabled and credentials exist.

    Returns None (Agent1 stays purely deterministic) when the flag is off or
    no LLM API key is configured — never raises at request time.
    """
    if not settings.agent1_llm_reconciliation:
        return None
    try:
        from app.agents.agent1.reconciler import Agent1Reconciler
        from app.services.llm_backends import build_chat_fn

        chat_fn = build_chat_fn(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        return Agent1Reconciler(
            chat_fn,
            confidence_threshold=settings.agent1_confidence_threshold,
            max_candidates=settings.agent1_max_reconcile_candidates,
        )
    except Exception:  # noqa: BLE001 — missing key/provider must not break search
        import logging

        logging.getLogger(__name__).warning(
            "agent1.reconciler.init_skipped", exc_info=True
        )
        return None
