"""Tests for GET /api/candidate-states."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus
from app.models.tools import McpTool

_DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Reference dictionary.",
    input_schema={"type": "object", "properties": {}},
)


async def _dict_handler(_inputs: dict[str, object]):
    return [
        {
            "setting": {
                "state": {
                    "candidate": [
                        {"id": 0, "label": "Import à traiter"},
                        {"id": 2, "label": "Qualifié"},
                        {"id": 7, "label": "Vivier"},
                        {"id": 8, "label": "A jouer"},
                        {"id": 10, "label": "Proposition refusé"},
                        {"id": 11, "label": "Ne plus contacter"},
                        {"id": 12, "label": "A SUPPRIMER"},
                    ]
                }
            }
        }
    ]


def _app_with_dictionary():
    app = create_app()
    settings = get_settings()
    app.state.mcp_client = MockMcpClient(
        tools=[_DICTIONARY_TOOL],
        handlers={"getDictionary": _dict_handler},
    )
    app.state.mcp_status = McpDependencyStatus(
        status="connected",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    return app


@pytest.mark.asyncio
async def test_candidate_states_returns_options_without_excluded_states() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app_with_dictionary()), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/candidate-states")

    assert response.status_code == 200
    body = response.json()
    labels = [state["label"] for state in body["states"]]
    assert "Vivier" in labels and "A jouer" in labels and "Qualifié" in labels
    assert "Ne plus contacter" not in labels
    assert "A SUPPRIMER" not in labels
    assert "Proposition refusé" not in labels
    assert all(
        set(state.keys()) == {"id", "label"} and isinstance(state["id"], str)
        for state in body["states"]
    )


@pytest.mark.asyncio
async def test_candidate_states_returns_503_when_dictionary_unavailable() -> None:
    app = create_app()
    settings = get_settings()
    # Mock client without a getDictionary handler -> McpToolError -> 503.
    app.state.mcp_client = MockMcpClient(tools=[])
    app.state.mcp_status = McpDependencyStatus(
        status="connected",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/candidate-states")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mcp_client_unavailable"
