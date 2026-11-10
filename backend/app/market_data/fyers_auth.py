"""FYERS OAuth v3 helpers.

The interactive login URL must be opened by the administrator. The auth code is
exchanged server-side; tokens are never exposed to the browser extension or the
mobile client.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError


class FyersAuthError(AppError):
    status_code = 502
    code = "fyers_auth_error"


def build_login_url(state: str = "oi-platform") -> str:
    settings = get_settings()
    if not settings.fyers_app_id:
        raise FyersAuthError("FYERS_APP_ID is not configured")
    params = {
        "client_id": settings.fyers_app_id,
        "redirect_uri": settings.fyers_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"https://api-t1.fyers.in/api/v3/generate-authcode?{urlencode(params)}"


def app_id_hash() -> str:
    settings = get_settings()
    if not settings.fyers_app_id or not settings.fyers_secret_key:
        raise FyersAuthError("FYERS credentials are not configured")
    return hashlib.sha256(f"{settings.fyers_app_id}:{settings.fyers_secret_key}".encode()).hexdigest()


def exchange_auth_code(auth_code: str) -> str:
    settings = get_settings()
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash(),
        "code": auth_code,
    }
    response = httpx.post(
        f"{settings.fyers_api_base.rstrip('/')}/token",
        json=payload,
        timeout=15,
    )
    if response.status_code >= 400:
        raise FyersAuthError("FYERS token exchange failed")
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise FyersAuthError("FYERS token exchange returned no access token")
    return token
