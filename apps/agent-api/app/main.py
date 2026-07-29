"""FastAPI application factory and module-level app instance."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import (
    chat_router,
    health_router,
    mcp_debug_router,
    mcp_tools_router,
    ready_router,
    search_router,
    search_stream_router,
)
from app.api.auth import (
    AuthenticationError,
    AuthorizationError,
    require_auth,
    validate_auth_settings,
)
from app.api.dependencies import McpClientUnavailableError
from app.config import get_settings
from app.mcp.factory import create_mcp_client
from app.models.api import ErrorEnvelope, ErrorPayload, McpDependencyStatus
from app.services.llm_backends import LlmBackendError, build_chat_fn
from app.services.llm_planner import StructuredLlmPlanner

logger = logging.getLogger(__name__)


# Third-party loggers that emit one-or-more INFO lines per MCP/LLM call and
# drown the agent's own decision logs. Quieted to WARNING regardless of level.
_NOISY_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "mcp",
    "mcp.client",
    "mcp.client.streamable_http",
    "openai",
    "uvicorn.access",
)

# Standard LogRecord attributes — anything else on the record is `extra=` data
# the call site attached (the actual decision payload), which the default
# formatter silently drops.
_RESERVED_LOG_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "message",
    "asctime",
    "taskName",
}


def _short_value(value: object, limit: int = 400) -> str:
    import json

    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _ExtraRenderingFormatter(logging.Formatter):
    """Append `extra={}` fields to each line so structured logs show content.

    The app logs decisions via ``logger.info("graph.plan_with_llm",
    extra={...})``; the default formatter prints only the static message and
    drops the dict. This renders those fields as ``key=value`` so the console
    actually shows what the agent decided.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: val
            for key, val in record.__dict__.items()
            if key not in _RESERVED_LOG_ATTRS and not key.startswith("_")
        }
        if not extras:
            return base
        rendered = " ".join(f"{k}={_short_value(v)}" for k, v in extras.items())
        return f"{base} | {rendered}"


def _configure_logging(level: str, *, verbose: bool = False) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    # Verbose mode renders the structured extra={} payloads as JSON on every
    # app log line; default mode keeps lines plain (the readable decision chain
    # comes from the agent.trace logger instead).
    formatter: logging.Formatter = (
        _ExtraRenderingFormatter(fmt) if verbose else logging.Formatter(fmt)
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Third-party noise is quieted in every mode.
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _close_client(client: object) -> None:
    """Close an MCP client supporting async aclose, sync close, or neither."""
    for attr in ("aclose", "close"):
        method = getattr(client, attr, None)
        if method is None:
            continue
        result = method()
        if inspect.isawaitable(result):
            await result
        return


def _sanitize_connect_error(exc: BaseException) -> str:
    """Produce a short, user-safe message for the health endpoint."""
    return f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(
        settings.log_level, verbose=settings.agent_trace == "verbose"
    )

    # Fail fast on ENABLE_AUTH=true without tenant/client ids — silently
    # starting an unauthenticated instance the operator believes is
    # protected would be worse than not starting.
    validate_auth_settings(settings)

    # The factory itself may raise McpClientNotImplementedError on a
    # configuration error (e.g. unsupported transport). That is a real
    # fail-fast case, not a connectivity blip, so we deliberately do not
    # catch it here.
    client = create_mcp_client(settings)

    if settings.use_mock_mcp:
        status_value: str = "mock"
        error: str | None = None
    else:
        status_value = "connected"
        error = None
        connect = getattr(client, "connect", None)
        if callable(connect):
            try:
                await connect()
            except (KeyboardInterrupt, SystemExit):
                # Never swallow process-control signals.
                raise
            except BaseException as exc:  # noqa: BLE001 — see comment
                # Treat any connect failure as "MCP unavailable" so the
                # process still comes up and /api/health stays reachable.
                # We deliberately widen to BaseException (above the
                # KeyboardInterrupt/SystemExit re-raise) so internal
                # asyncio.CancelledError from the MCP SDK's TaskGroup is
                # also captured. Without this, FastAPI startup would abort
                # and /api/health would be unreachable.
                logger.exception("mcp.connect_failed")
                # Best-effort close in case partial state was allocated.
                try:
                    await _close_client(client)
                except Exception:  # noqa: BLE001
                    logger.exception("mcp.close_after_failed_connect_failed")
                status_value = "unavailable"
                error = _sanitize_connect_error(exc)

    app.state.mcp_client = client
    app.state.mcp_status = McpDependencyStatus(
        status=status_value,  # type: ignore[arg-type]
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=error,
    )

    # Build the LLM planner when configured. Fail fast on misconfig so
    # we never silently fall back to the deterministic planner when the
    # operator asked for LLM planning.
    if settings.use_llm_planner:
        try:
            chat_fn = build_chat_fn(
                provider=settings.llm_provider,
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                temperature=settings.llm_temperature,
                timeout_seconds=settings.llm_timeout_seconds,
            )
        except LlmBackendError:
            logger.exception("llm_planner.init_failed")
            raise
        app.state.llm_planner = StructuredLlmPlanner(
            chat_fn=chat_fn, role=settings.llm_planner_role
        )
        logger.info(
            "llm_planner.ready",
            extra={
                "provider": settings.llm_provider,
                "model": settings.llm_model,
            },
        )
    else:
        app.state.llm_planner = None

    try:
        yield
    finally:
        bound = getattr(app.state, "mcp_client", None)
        if bound is not None:
            try:
                await _close_client(bound)
            except Exception:  # noqa: BLE001
                logger.exception("mcp.close_failed")
        app.state.mcp_client = None
        app.state.mcp_status = None
        app.state.llm_planner = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sijo Agent API",
        version=__version__,
        description=(
            "LangGraph-orchestrated natural-language search over BoondManager "
            "via MCP tools."
        ),
        lifespan=lifespan,
    )

    # Health and readiness stay unauthenticated (probes); everything
    # else requires a valid Entra ID token when ENABLE_AUTH=true.
    protected = [Depends(require_auth)]
    app.include_router(health_router)
    app.include_router(ready_router)
    app.include_router(search_router, dependencies=protected)
    app.include_router(search_stream_router, dependencies=protected)
    app.include_router(mcp_tools_router, dependencies=protected)
    # Debug router is always registered but its handler returns 404
    # when ENABLE_MCP_DEBUG_ENDPOINTS is false so its existence stays
    # invisible in production.
    app.include_router(mcp_debug_router, dependencies=protected)
    app.include_router(chat_router, dependencies=protected)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="invalid_request",
                message="The request payload failed validation.",
                details={"errors": jsonable_encoder(exc.errors())},
            )
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=jsonable_encoder(envelope),
        )

    @app.exception_handler(AuthenticationError)
    async def _authentication_handler(
        _: Request, exc: AuthenticationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorPayload(code=exc.code, message=exc.message)
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=jsonable_encoder(envelope),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(AuthorizationError)
    async def _authorization_handler(
        _: Request, exc: AuthorizationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorPayload(code=exc.code, message=exc.message)
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=jsonable_encoder(envelope),
        )

    @app.exception_handler(McpClientUnavailableError)
    async def _mcp_unavailable_handler(
        _: Request, __: McpClientUnavailableError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="mcp_client_unavailable",
                message=(
                    "The MCP client is not initialized. The Agent API cannot "
                    "serve search requests until an MCP client is bound."
                ),
            )
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(envelope),
        )

    return app


app = create_app()
