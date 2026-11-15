"""FYERS OAuth v3 helpers.

Flow (official, browser-based): the administrator opens the authorization URL,
FYERS redirects back to ``FYERS_REDIRECT_URI`` with a one-time ``auth_code``,
and the backend exchanges it for an access token. Tokens are never exposed to
the browser extension, the mobile client or the login page.

The ``state`` parameter is a short-lived, signed JWT (HS256, signed with
``JWT_SECRET``). It is validated before the authorization code is used, which
prevents cross-site request forgery against the callback.

No username/password/TOTP automation happens here: the user always completes
the official FYERS login page themselves.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

STATE_TYPE = "fyers_oauth_state"
STATE_AUDIENCE = "fyers-oauth"
STATE_ISSUER = "oi-intelligence-platform"
DEFAULT_STATE_TTL_SECONDS = 300
MIN_STATE_TTL_SECONDS = 60


class FyersAuthError(AppError):
    status_code = 502
    code = "fyers_auth_error"


class FyersOAuthStateError(FyersAuthError):
    """The OAuth state is missing, expired, tampered with or of the wrong type."""

    status_code = 400
    code = "fyers_invalid_state"


class FyersConfigError(FyersAuthError):
    status_code = 503
    code = "fyers_not_configured"


@dataclass(frozen=True)
class OAuthState:
    """A signed, short-lived OAuth state value."""

    state: str
    expires_at: datetime


@dataclass(frozen=True)
class OAuthLogin:
    """Authorization URL plus the metadata the admin UI may display."""

    url: str
    state: str
    expires_at: datetime


@dataclass(frozen=True)
class TokenGrant:
    """Result of a successful authorization-code exchange."""

    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None


def _state_ttl_seconds() -> int:
    configured = int(get_settings().fyers_oauth_state_ttl_seconds or DEFAULT_STATE_TTL_SECONDS)
    return max(MIN_STATE_TTL_SECONDS, configured)


def create_oauth_state(
    subject: str | None = None,
    *,
    ttl_seconds: int | None = None,
    now: datetime | None = None,
) -> OAuthState:
    """Create a signed, short-lived state token for one login attempt."""
    settings = get_settings()
    issued = now or datetime.now(timezone.utc)
    ttl = max(MIN_STATE_TTL_SECONDS, int(ttl_seconds or _state_ttl_seconds()))
    expires = issued + timedelta(seconds=ttl)
    payload = {
        "type": STATE_TYPE,
        "iss": STATE_ISSUER,
        "aud": STATE_AUDIENCE,
        "sub": subject or "admin",
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_hex(16),
        "nonce": secrets.token_urlsafe(16),
    }
    state = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return OAuthState(state=state, expires_at=expires)


def validate_oauth_state(state: str | None) -> dict:
    """Decode and verify a state token. Raises :class:`FyersOAuthStateError`."""
    if not state:
        raise FyersOAuthStateError("The FYERS callback did not include an OAuth state")
    settings = get_settings()
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=STATE_AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        raise FyersOAuthStateError(
            "The FYERS login link expired before it was completed; start the login again"
        ) from exc
    except jwt.PyJWTError as exc:
        raise FyersOAuthStateError(
            "The FYERS login state is invalid; start the login again from the admin panel"
        ) from exc
    if payload.get("type") != STATE_TYPE or payload.get("iss") != STATE_ISSUER:
        raise FyersOAuthStateError(
            "The FYERS login state is not valid for this application; start the login again"
        )
    return payload


def build_login_url(state: str | None = None) -> str:
    """Authorization URL for the official FYERS login page.

    ``state`` is created on demand so existing callers keep working.
    """
    settings = get_settings()
    if not settings.fyers_app_id:
        raise FyersConfigError("FYERS_APP_ID is not configured")
    state = state or create_oauth_state().state
    params = {
        "client_id": settings.fyers_app_id,
        "redirect_uri": settings.fyers_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{settings.fyers_api_base.rstrip('/')}/generate-authcode?{urlencode(params)}"


def create_login_url(subject: str | None = None) -> OAuthLogin:
    """Signed state plus the authorization URL in one call."""
    state = create_oauth_state(subject)
    return OAuthLogin(
        url=build_login_url(state.state),
        state=state.state,
        expires_at=state.expires_at,
    )


def app_id_hash() -> str:
    settings = get_settings()
    if not settings.fyers_app_id or not settings.fyers_secret_key:
        raise FyersConfigError("FYERS_APP_ID and FYERS_SECRET_KEY must both be configured")
    return hashlib.sha256(
        f"{settings.fyers_app_id}:{settings.fyers_secret_key}".encode()
    ).hexdigest()


def _fy_message(payload: dict, default: str) -> str:
    message = payload.get("message") or payload.get("error") or default
    return str(message)[:200]


def exchange_auth_code(auth_code: str) -> TokenGrant:
    """Exchange a one-time authorization code server-side.

    The access token is returned to the caller for encrypted storage only. It is
    never logged and never placed in an error message.
    """
    settings = get_settings()
    if not auth_code or not auth_code.strip():
        raise FyersOAuthStateError("The FYERS callback did not include an authorization code")
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash(),
        "code": auth_code.strip(),
    }
    try:
        response = httpx.post(
            # FYERS v3 exchanges the authorization code at /validate-authcode.
            # Posting to /token returns a blanket 401 (-16) for every request.
            f"{settings.fyers_api_base.rstrip('/')}/validate-authcode",
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        logger.warning("fyers_token_endpoint_unreachable", extra={"error": type(exc).__name__})
        raise FyersAuthError("The FYERS token endpoint could not be reached") from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        # Log FYERS's own error code/message so a rejected login can be
        # diagnosed. The payload never contains the secret or the issued token.
        detail = data if isinstance(data, dict) else {}
        logger.warning(
            "fyers_token_exchange_rejected",
            extra={
                "status_code": response.status_code,
                "fyers_code": detail.get("code"),
                "fyers_message": _fy_message(detail, "")[:200],
            },
        )
        raise FyersAuthError(
            f"FYERS rejected the authorization code ({response.status_code}): "
            f"{_fy_message(data, 'token exchange failed')}"
        )
    if not isinstance(data, dict) or data.get("s") != "ok":
        message = _fy_message(data if isinstance(data, dict) else {}, "unexpected response")
        raise FyersAuthError(f"FYERS token exchange failed: {message}")

    token = data.get("access_token")
    if not token or not isinstance(token, str):
        raise FyersAuthError("FYERS token exchange returned no access token")

    expires_in = data.get("expires_in")
    try:
        expires_in_value = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in_value = None

    refresh_token = data.get("refresh_token")
    return TokenGrant(
        access_token=token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        expires_in=expires_in_value,
    )
