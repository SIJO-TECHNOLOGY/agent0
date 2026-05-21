"""Tests for the MCP client factory."""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.mcp.factory import McpClientNotImplementedError, create_mcp_client
from app.mcp.mock_client import MockMcpClient
from app.mcp.remote_client import RemoteMcpClient


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "use_mock_mcp": True,
        "mcp_server_url": "http://localhost:8001/mcp",
        "mcp_transport": "streamable_http",
        "mcp_timeout_seconds": 5.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_factory_returns_mock_when_use_mock_mcp_true() -> None:
    client = create_mcp_client(_settings(use_mock_mcp=True))

    assert isinstance(client, MockMcpClient)


def test_factory_returns_remote_client_when_use_mock_mcp_false() -> None:
    client = create_mcp_client(
        _settings(
            use_mock_mcp=False,
            mcp_server_url="http://remote.test:9000/mcp",
            mcp_transport="streamable_http",
            mcp_timeout_seconds=7.5,
        )
    )

    assert isinstance(client, RemoteMcpClient)
    assert client.url == "http://remote.test:9000/mcp"
    assert client._timeout_seconds == 7.5  # type: ignore[attr-defined]


def test_factory_raises_when_use_mock_mcp_false_without_url() -> None:
    settings = _settings(use_mock_mcp=False, mcp_server_url="")

    with pytest.raises(McpClientNotImplementedError) as excinfo:
        create_mcp_client(settings)

    assert "MCP_SERVER_URL" in str(excinfo.value)


def test_factory_raises_when_transport_unsupported() -> None:
    settings = _settings(
        use_mock_mcp=False,
        mcp_server_url="http://remote.test/mcp",
        mcp_transport="sse",
    )

    with pytest.raises(McpClientNotImplementedError) as excinfo:
        create_mcp_client(settings)

    message = str(excinfo.value)
    assert "sse" in message
    assert "streamable_http" in message
