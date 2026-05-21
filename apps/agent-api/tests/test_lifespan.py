"""Tests for the FastAPI lifespan: startup binds MCP client, shutdown closes it."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

import app.main as main_module
from app.config.settings import Settings
from app.main import lifespan
from app.mcp.client import McpTransientError
from app.mcp.mock_client import MockMcpClient


def _real_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "use_mock_mcp": False,
        "mcp_server_url": "http://remote.test/mcp",
        "mcp_transport": "streamable_http",
        "mcp_timeout_seconds": 2.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_lifespan_binds_mcp_client_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(
            use_mock_mcp=True,
            mcp_server_url="http://localhost:8001/mcp",
            mcp_transport="streamable_http",
        ),
    )
    app = FastAPI()

    async with lifespan(app):
        assert isinstance(app.state.mcp_client, MockMcpClient)
        assert app.state.mcp_status.status == "mock"
        assert app.state.mcp_status.error is None

    assert app.state.mcp_client is None
    assert app.state.mcp_status is None


@pytest.mark.asyncio
async def test_lifespan_closes_async_client_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = {"count": 0}

    class AsyncClosable:
        async def aclose(self) -> None:
            closed["count"] += 1

    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: AsyncClosable())

    app = FastAPI()
    async with lifespan(app):
        assert isinstance(app.state.mcp_client, AsyncClosable)

    assert closed["count"] == 1
    assert app.state.mcp_client is None


@pytest.mark.asyncio
async def test_lifespan_closes_sync_client_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = {"count": 0}

    class SyncClosable:
        def close(self) -> None:
            closed["count"] += 1

    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: SyncClosable())

    app = FastAPI()
    async with lifespan(app):
        assert isinstance(app.state.mcp_client, SyncClosable)

    assert closed["count"] == 1
    assert app.state.mcp_client is None


@pytest.mark.asyncio
async def test_lifespan_client_without_close_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoClose:
        pass

    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: NoClose())

    app = FastAPI()
    async with lifespan(app):
        assert isinstance(app.state.mcp_client, NoClose)

    assert app.state.mcp_client is None


@pytest.mark.asyncio
async def test_lifespan_real_mode_awaits_connect_and_marks_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class ConnectableClient:
        async def connect(self) -> None:
            events.append("connect")

        async def aclose(self) -> None:
            events.append("aclose")

    monkeypatch.setattr(main_module, "get_settings", lambda: _real_settings())
    monkeypatch.setattr(
        main_module, "create_mcp_client", lambda _s: ConnectableClient()
    )

    app = FastAPI()
    async with lifespan(app):
        assert events == ["connect"]
        assert isinstance(app.state.mcp_client, ConnectableClient)
        assert app.state.mcp_status.status == "connected"
        assert app.state.mcp_status.url == "http://remote.test/mcp"
        assert app.state.mcp_status.transport == "streamable_http"
        assert app.state.mcp_status.error is None

    assert events == ["connect", "aclose"]
    assert app.state.mcp_client is None
    assert app.state.mcp_status is None


@pytest.mark.asyncio
async def test_lifespan_real_mode_marks_unavailable_when_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_events: list[str] = []

    class FailingClient:
        async def connect(self) -> None:
            raise McpTransientError("server down")

        async def aclose(self) -> None:
            close_events.append("aclose")

    monkeypatch.setattr(main_module, "get_settings", lambda: _real_settings())
    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: FailingClient())

    app = FastAPI()
    # Must NOT raise: the app stays up so /api/health remains reachable.
    async with lifespan(app):
        assert app.state.mcp_client is None
        assert app.state.mcp_status.status == "unavailable"
        assert "server down" in app.state.mcp_status.error
        assert app.state.mcp_status.url == "http://remote.test/mcp"

    # Failed-connect path also attempts a best-effort close.
    assert close_events == ["aclose"]


@pytest.mark.asyncio
async def test_lifespan_real_mode_close_failure_during_failed_connect_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second exception during cleanup must not break startup."""

    class DoublyBadClient:
        async def connect(self) -> None:
            raise McpTransientError("server down")

        async def aclose(self) -> None:
            raise RuntimeError("close also broken")

    monkeypatch.setattr(main_module, "get_settings", lambda: _real_settings())
    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: DoublyBadClient())

    app = FastAPI()
    async with lifespan(app):
        assert app.state.mcp_client is None
        assert app.state.mcp_status.status == "unavailable"


@pytest.mark.asyncio
async def test_lifespan_real_mode_marks_unavailable_when_connect_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense in depth: even if `connect()` lets a CancelledError escape
    (e.g. SDK upgrade changes mapping), the lifespan must still keep the
    app alive and mark MCP unavailable."""

    class CancelClient:
        async def connect(self) -> None:
            raise asyncio.CancelledError("simulated cancel during init")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(main_module, "get_settings", lambda: _real_settings())
    monkeypatch.setattr(main_module, "create_mcp_client", lambda _s: CancelClient())

    app = FastAPI()
    # Must NOT propagate CancelledError out of lifespan.
    async with lifespan(app):
        assert app.state.mcp_client is None
        assert app.state.mcp_status.status == "unavailable"
        assert "CancelledError" in app.state.mcp_status.error
