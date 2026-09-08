"""Microsoft Entra ID bearer-token validation.

`require_auth` is attached as a router-level dependency to every /api/*
router except health and readiness (see `app.main.create_app`). When
`ENABLE_AUTH=false` (the default, for local development and tests) it is
a no-op.

Validation of an incoming `Authorization: Bearer <jwt>`:

1. Signature against the tenant's published JWKS keys (cached by
   `jwt.PyJWKClient`), plus `exp`/`nbf`.
2. `aud` must be this API: `api://<client-id>` or the bare client id
   (Entra emits either form depending on how the scope was requested).
3. `iss` must be this tenant. Both the v2.0 issuer
   (login.microsoftonline.com/<tenant>/v2.0) and the v1.0 issuer
   (sts.windows.net/<tenant>/) are accepted because the app
   registration's `accessTokenAcceptedVersion` controls which one Entra
   uses for custom-API scopes.
4. Optionally, the account's email domain: a single-tenant registration
   already limits sign-in to the tenant, but invited guest accounts
   live in the tenant too — `AUTH_ALLOWED_EMAIL_DOMAIN` closes that gap.

Failures raise `AuthenticationError` (401) or `AuthorizationError`
(403), both translated to the standard error envelope by handlers in
`app.main`. Token claim values are never echoed back to the client and
never logged above DEBUG.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock

import jwt
from fastapi import Depends, Request

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_ALGORITHMS = ["RS256"]


class AuthConfigurationError(RuntimeError):
    """ENABLE_AUTH=true but tenant/client ids are missing. Fail-fast at startup."""


class AuthenticationError(Exception):
    """Missing or invalid credentials → HTTP 401."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthorizationError(Exception):
    """Valid token but the account is not allowed → HTTP 403."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AuthenticatedUser:
    """Sanitized identity extracted from a validated token.

    ``oid`` is the Entra account's immutable object id — the key used
    to partition per-user data (it survives username changes, unlike
    the email address).
    """

    username: str
    name: str | None = None
    oid: str = ""


# Identity used when ENABLE_AUTH=false (local development, tests):
# everything is stored under one deterministic user.
DEV_USER = AuthenticatedUser(username="dev", name=None, oid="dev")


# Environments where running unauthenticated is a deliberate convenience
# (local development, tests, CI). Anything else — production, staging, or an
# unrecognized value — is treated as needing server-side auth, so an operator
# can never *silently* ship an unauthenticated instance by forgetting to set
# ENABLE_AUTH.
_AUTH_OPTIONAL_ENVS: frozenset[str] = frozenset(
    {"local", "dev", "development", "test", "testing", "ci"}
)


def validate_auth_settings(settings: Settings) -> None:
    """Validate the auth configuration at startup; fail fast on an unsafe combo.

    Two failure modes, both raising `AuthConfigurationError`:

    * `ENABLE_AUTH=false` outside a known local/dev/test environment
      (`APP_ENV`) — production must not run without server-side token
      validation; frontend MSAL alone is not a security boundary.
    * `ENABLE_AUTH=true` without `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`.
    """
    env = (settings.app_env or "").strip().lower()
    if not settings.enable_auth:
        if env not in _AUTH_OPTIONAL_ENVS:
            raise AuthConfigurationError(
                f"ENABLE_AUTH must be true when APP_ENV={settings.app_env!r}: "
                "server-side authentication cannot be disabled outside "
                "local/dev/test environments."
            )
        return
    missing = [
        name
        for name, value in (
            ("ENTRA_TENANT_ID", settings.entra_tenant_id),
            ("ENTRA_CLIENT_ID", settings.entra_client_id),
        )
        if not value
    ]
    if missing:
        raise AuthConfigurationError(
            "ENABLE_AUTH=true requires " + " and ".join(missing) + " to be set."
        )


# One PyJWKClient per JWKS URL, shared across requests: it caches the
# tenant's signing keys and refreshes them on unknown-kid lookups.
_JWKS_CLIENTS: dict[str, jwt.PyJWKClient] = {}
_JWKS_LOCK = Lock()


def _jwks_client(tenant_id: str) -> jwt.PyJWKClient:
    url = (
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    )
    with _JWKS_LOCK:
        client = _JWKS_CLIENTS.get(url)
        if client is None:
            client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
            _JWKS_CLIENTS[url] = client
        return client


def _accepted_issuers(tenant_id: str) -> set[str]:
    return {
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    }


def _decode(token: str, settings: Settings) -> dict[str, object]:
    tenant_id = settings.entra_tenant_id or ""
    client_id = settings.entra_client_id or ""
    try:
        signing_key = _jwks_client(tenant_id).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            audience=[f"api://{client_id}", client_id],
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        # Reason goes to debug logs only; the client gets a generic 401.
        logger.debug("auth.token_rejected: %s", type(exc).__name__)
        raise AuthenticationError(
            "invalid_token",
            "The access token is missing, expired, or invalid.",
        ) from exc
    issuer = str(claims.get("iss", ""))
    if issuer not in _accepted_issuers(tenant_id):
        logger.debug("auth.token_rejected: unexpected issuer")
        raise AuthenticationError(
            "invalid_token",
            "The access token is missing, expired, or invalid.",
        )
    return claims


def _check_domain(claims: dict[str, object], settings: Settings) -> str:
    username = str(
        claims.get("preferred_username") or claims.get("upn") or ""
    )
    domain = settings.auth_allowed_email_domain
    if domain and not username.lower().endswith("@" + domain.lower()):
        raise AuthorizationError(
            "account_not_allowed",
            f"This service is restricted to @{domain} accounts.",
        )
    return username


def require_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser | None:
    """FastAPI dependency: validate the bearer token when auth is enabled.

    Returns the authenticated identity, or None when ENABLE_AUTH=false.
    Runs in the threadpool (sync def) because the first JWKS fetch is
    blocking I/O; subsequent calls hit the in-process key cache.
    """
    if not settings.enable_auth:
        return None

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError(
            "missing_token",
            "An Authorization: Bearer access token is required.",
        )

    claims = _decode(token.strip(), settings)
    username = _check_domain(claims, settings)
    name = claims.get("name")
    user = AuthenticatedUser(
        username=username,
        name=str(name) if name else None,
        oid=str(claims.get("oid") or username),
    )
    # Expose the identity to route handlers (get_current_user): the
    # router-level dependency's return value is not otherwise reachable.
    request.state.current_user = user
    return user


def get_current_user(request: Request) -> AuthenticatedUser:
    """Identity for the current request.

    `require_auth` stores the validated user on request.state; when
    auth is disabled it never does, and everything belongs to the
    deterministic DEV_USER.
    """
    user = getattr(request.state, "current_user", None)
    return user if isinstance(user, AuthenticatedUser) else DEV_USER
