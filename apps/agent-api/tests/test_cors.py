"""CORS origins come from settings, not hardcoded literals."""

from __future__ import annotations

from httpx import AsyncClient

from app.config import Settings


def test_cors_origins_default() -> None:
    settings = Settings(use_mock_mcp=True)
    assert settings.cors_origins == [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]


def test_cors_origins_parses_and_strips() -> None:
    settings = Settings(
        use_mock_mcp=True,
        cors_allowed_origins=(
            " http://localhost:5500 , https://assistant.sijo.fr ,"
        ),
    )
    assert settings.cors_origins == [
        "http://localhost:5500",
        "https://assistant.sijo.fr",
    ]


async def test_allowed_origin_gets_cors_headers(client: AsyncClient) -> None:
    response = await client.get(
        "/api/health", headers={"Origin": "http://localhost:5500"}
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:5500"
    )


async def test_unknown_origin_gets_no_cors_headers(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/health", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
