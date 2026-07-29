"""Entra ID bearer-token enforcement on the API routes.

Tokens are signed locally with a test RSA key; the JWKS lookup is
monkeypatched so no network is involved. The claims mirror what Entra
issues for a single-tenant SPA requesting `api://<client>/access_as_user`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from types import SimpleNamespace

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from app.api import auth as auth_module
from app.api.auth import AuthConfigurationError, validate_auth_settings
from app.config import Settings, get_settings
from app.main import create_app
from app.mcp.mock_client import MockMcpClient
from app.models.api import McpDependencyStatus

TENANT_ID = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def fake_jwks(monkeypatch: pytest.MonkeyPatch, rsa_key: rsa.RSAPrivateKey):
    """Route JWKS lookups to the test public key instead of Microsoft."""
    public_pem = rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fake = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_pem)
    )
    monkeypatch.setattr(auth_module, "_jwks_client", lambda tenant_id: fake)
    return fake


def make_token(
    rsa_key: rsa.RSAPrivateKey,
    *,
    username: str = "recruiter@sijo.fr",
    audience: str = f"api://{CLIENT_ID}",
    issuer: str = ISSUER_V2,
    expires_in: int = 600,
    drop_username: bool = False,
) -> str:
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + expires_in,
        "iat": int(time.time()) - 5,
        "name": "Test Recruiter",
        "preferred_username": username,
        "scp": "access_as_user",
    }
    if drop_username:
        claims.pop("preferred_username")
    return jwt.encode(claims, rsa_key, algorithm="RS256")


def auth_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "use_mock_mcp": True,
        "enable_auth": True,
        "entra_tenant_id": TENANT_ID,
        "entra_client_id": CLIENT_ID,
        "auth_allowed_email_domain": "sijo.fr",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest_asyncio.fixture()
async def auth_client(fake_jwks) -> AsyncIterator[AsyncClient]:
    """App with ENABLE_AUTH=true and mock MCP bound (lifespan bypassed)."""
    app = create_app()
    settings = auth_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.mcp_client = MockMcpClient()
    app.state.mcp_status = McpDependencyStatus(
        status="mock",
        url=settings.mcp_server_url,
        transport=settings.mcp_transport,
        error=None,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_auth_disabled_leaves_routes_open(client: AsyncClient) -> None:
    response = await client.get("/api/conversations")
    assert response.status_code == 200


async def test_missing_token_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/conversations")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_malformed_header_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": "Token abc"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


async def test_garbage_token_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/conversations",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_valid_token_accepted(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key)
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_bare_client_id_audience_accepted(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, audience=CLIENT_ID)
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_v1_issuer_accepted(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, issuer=ISSUER_V1)
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_wrong_audience_rejected(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, audience="00000003-0000-0000-c000-000000000000")
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_foreign_tenant_issuer_rejected(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(
        rsa_key,
        issuer="https://login.microsoftonline.com/other-tenant/v2.0",
    )
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_expired_token_rejected(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, expires_in=-60)
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_wrong_domain_rejected(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, username="intruder@gmail.com")
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_not_allowed"


async def test_missing_username_claim_rejected(
    auth_client: AsyncClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = make_token(rsa_key, drop_username=True)
    response = await auth_client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_not_allowed"


async def test_stream_route_protected(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/search/stream", json={"query": "java developer"}
    )
    assert response.status_code == 401


async def test_search_route_protected(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/search", json={"query": "java developer"}
    )
    assert response.status_code == 401


async def test_health_and_ready_stay_open(auth_client: AsyncClient) -> None:
    health = await auth_client.get("/api/health")
    ready = await auth_client.get("/api/ready")
    assert health.status_code == 200
    assert ready.status_code == 200


def test_validate_auth_settings_fails_fast_on_missing_ids() -> None:
    with pytest.raises(AuthConfigurationError):
        validate_auth_settings(
            auth_settings(entra_tenant_id=None, entra_client_id=None)
        )


def test_validate_auth_settings_noop_when_disabled() -> None:
    validate_auth_settings(Settings(use_mock_mcp=True, enable_auth=False))
