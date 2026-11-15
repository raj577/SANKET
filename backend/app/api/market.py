"""Market-data endpoints.

Prices are only reported when they were actually observed. A configured but
unpolled symbol returns no price rather than a fabricated one.

FYERS OAuth (data-only) lives here too:

* ``GET /market/fyers/login-url`` (admin) - signed state + authorization URL
* ``GET /market/fyers/callback``         - validates state, exchanges the code
* ``GET /market/fyers/status`` (admin)   - secret-free authentication status

The access token is encrypted at rest and is never returned by any endpoint.
"""
from __future__ import annotations

import hashlib
import html
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, require_admin
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.timeutils import to_ist, utcnow
from app.db.session import get_db
from app.market_data import fyers_auth
from app.market_data.fyers_client import FyersTokenStore
from app.market_data.fyers_token_store import FyersTokenStoreError
from app.market_data.provider import provider_status
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.models.user import User
from app.schemas.admin import PriceOut
from app.schemas.serializers import price_freshness
from app.services import audit_service, settings_service

logger = get_logger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str | None, *, limit: int = 180) -> str:
    """Sanitise text that originates from FYERS or a query string."""
    if not value:
        return ""
    text = _CONTROL_CHARS.sub(" ", str(value)).strip()
    return text[:limit]


@router.get("/status")
def market_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    settings = get_settings()
    provider, configured, stream_ready = provider_status()
    active = db.scalar(
        select(func.count(PublishedSignal.id)).where(
            PublishedSignal.status == SignalStatus.ACTIVE.value
        )
    ) or 0
    freshest = db.scalar(
        select(func.max(PublishedSignal.price_updated_at)).where(
            PublishedSignal.status == SignalStatus.ACTIVE.value
        )
    )
    transport = (
        settings.market_data_transport
        if stream_ready and settings.market_data_transport == "websocket"
        else "rest"
    )
    market_settings = settings_service.get_value(db, "market_data")
    return {
        "provider": provider.upper(),
        "configured": configured,
        "stream_ready": stream_ready,
        "transport": transport,
        "tracking_enabled": bool(market_settings.get("tracking_enabled", False)),
        "poll_interval_seconds": settings.tracking_poll_seconds,
        "active_signals": int(active),
        "last_price_update": freshest,
    }


@router.get("/prices/{symbol}", response_model=PriceOut)
def get_price(
    symbol: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PriceOut:
    normalized = symbol.strip().upper()
    signal = db.scalar(
        select(PublishedSignal)
        .where(func.upper(PublishedSignal.symbol) == normalized)
        .order_by(PublishedSignal.published_at.desc())
        .limit(1)
    )
    if signal is None:
        raise NotFoundError("No published signal exists for this symbol")
    return PriceOut(
        symbol=signal.symbol,
        ltp=signal.current_ltp,
        updated_at=signal.price_updated_at,
        freshness=price_freshness(signal),
        signal_id=signal.id,
        direction=signal.direction,
    )


# ------------------------------------------------------------------- FYERS OAuth


@router.get("/fyers/login-url")
def fyers_login_url(admin: User = Depends(require_admin)) -> dict:
    """Administrator-only: signed state plus the official FYERS login URL."""
    login = fyers_auth.create_login_url(subject=str(admin.id))
    return {
        "url": login.url,
        "state": login.state,
        "expires_at": login.expires_at,
    }


@router.get("/fyers/status")
def fyers_status(_: User = Depends(require_admin)) -> dict:
    """Administrator-only: authentication status. Never includes the token."""
    settings = get_settings()
    status = FyersTokenStore().status()
    provider, market_configured, stream_ready = provider_status()
    payload = status.as_dict()
    payload.update(
        {
            "provider": provider.upper(),
            "app_id": settings.fyers_app_id,
            "redirect_uri": settings.fyers_redirect_uri,
            "login_available": bool(settings.fyers_app_id),
            "market_data_configured": market_configured,
            "stream_ready": stream_ready,
        }
    )
    return payload


@router.post("/fyers/exchange")
def exchange_fyers_code(
    code: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Admin-panel fallback for a pasted authorization code.

    Kept for compatibility with the existing admin UI; the browser callback is
    the normal path and additionally validates the OAuth state.
    """
    grant = fyers_auth.exchange_auth_code(code)
    record = FyersTokenStore().save(
        grant.access_token,
        expires_in=grant.expires_in,
        source="manual_exchange",
    )
    audit_service.record(
        db,
        action="FYERS_TOKEN_UPDATED",
        entity_type="market_data",
        details={
            "provider": "FYERS",
            "via": "manual_exchange",
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        },
        user=admin,
    )
    db.commit()
    return {
        "detail": "FYERS access token stored",
        "updated_at": utcnow(),
        "expires_at": record.expires_at,
    }


def _callback_page(title: str, message: str, *, ok: bool) -> HTMLResponse:
    color = "#137333" if ok else "#b3261e"
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{safe_title}</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: #f6f7f9;
         display: grid; place-items: center; min-height: 100vh; margin: 0; }}
  .box {{ background: #fff; padding: 32px 40px; border-radius: 12px;
          box-shadow: 0 8px 30px rgba(0,0,0,.08); max-width: 520px; }}
  h1 {{ color: {color}; font-size: 20px; margin: 0 0 10px; }}
  p {{ color: #444; line-height: 1.5; margin: 0; }}
</style></head>
<body><div class="box"><h1>{safe_title}</h1><p>{safe_message}</p></div></body></html>"""
    return HTMLResponse(content=page, status_code=200 if ok else 400)


def _code_fingerprint(value: str) -> dict:
    """Describe an authorization code without logging the code itself."""
    return {
        "length": len(value),
        "sha256_12": hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12],
        "has_percent": "%" in value,
        "has_plus": "+" in value,
        "has_space": " " in value,
    }


def _fyers_failure(
    s: str | None,
    error: str | None,
    description: str | None,
    message: str | None,
) -> str | None:
    """Describe a FYERS-reported failure without echoing anything sensitive."""
    if error:
        return (
            f"FYERS did not authorise the request: {_clean(description or error)}. "
            "Start again from the admin panel."
        )
    if s and s.lower() not in {"ok", "success"}:
        return (
            f"FYERS returned an error: {_clean(message or f'status {s}')}. "
            "Start again from the admin panel."
        )
    return None


@router.get("/fyers/callback", response_class=HTMLResponse, include_in_schema=False)
def fyers_callback(
    request: Request,
    code: str | None = None,
    auth_code: str | None = None,
    state: str | None = None,
    s: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    message: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """OAuth redirect target registered with FYERS.

    The signed state is validated before the one-time authorization code is
    used. The code is exchanged server-side and the resulting access token is
    stored encrypted; it is never returned to the browser.
    """
    try:
        claims = fyers_auth.validate_oauth_state(state)
    except fyers_auth.FyersOAuthStateError as exc:
        logger.warning("fyers_oauth_state_rejected", extra={"reason": _clean(exc.message, limit=80)})
        return _callback_page("FYERS login link expired or invalid", exc.message, ok=False)

    failure = _fyers_failure(s, error, error_description, message)
    if failure:
        logger.warning("fyers_oauth_reported_error", extra={"status": _clean(s or error, limit=40)})
        return _callback_page("FYERS login was not completed", failure, ok=False)

    # FYERS appends BOTH `code=200` (the HTTP status of the login request) and
    # `auth_code=<one-time code>`. Prefer auth_code: sending the numeric status
    # to the token endpoint yields -437 "invalid auth code" on every login.
    auth_code_value = (auth_code or "").strip()
    status_value = (code or "").strip()
    supplied = auth_code_value or ("" if status_value.isdigit() else status_value)
    if not supplied:
        return _callback_page(
            "FYERS login failed",
            "No authorization code was returned. Start the login again from the admin panel.",
            ok=False,
        )

    # Temporary diagnostic: distinguish a reused/expired code from a code that
    # was truncated or re-encoded in transit. Never logs the code itself.
    logger.warning(
        "fyers_callback_code_received",
        extra={
            "supplied": _code_fingerprint(supplied),
            "raw_code": _code_fingerprint(code) if code else None,
            "raw_auth_code": _code_fingerprint(auth_code) if auth_code else None,
            "raw_query_length": len(request.url.query),
            "state_length": len(state or ""),
        },
    )

    try:
        grant = fyers_auth.exchange_auth_code(supplied)
    except AppError as exc:
        # Includes FyersAuthError: expired/duplicate codes, rejected app, etc.
        logger.warning("fyers_code_exchange_failed", extra={"code": exc.code})
        return _callback_page(
            "FYERS login failed",
            f"{_clean(exc.message)} This login link may have expired, or it may have already "
            "been used. Start the login again from the admin panel.",
            ok=False,
        )
    except Exception:  # never leak an unexpected traceback to the browser
        logger.exception("fyers_code_exchange_unexpected")
        return _callback_page(
            "FYERS login failed",
            "The authorization code could not be exchanged. Start the login again from the "
            "admin panel, and check the backend logs if this repeats.",
            ok=False,
        )

    try:
        record = FyersTokenStore().save(
            grant.access_token,
            expires_in=grant.expires_in,
            source="oauth_callback",
        )
    except FyersTokenStoreError as exc:
        logger.error("fyers_token_store_failed", extra={"reason": str(exc)})
        return _callback_page(
            "FYERS authorised, but the token was not stored",
            f"{_clean(str(exc))}. Configure FYERS_TOKEN_ENCRYPTION_KEY and log in again. "
            "The access token was discarded and was never written in plaintext.",
            ok=False,
        )

    try:
        audit_service.record(
            db,
            action="FYERS_TOKEN_UPDATED",
            entity_type="market_data",
            details={
                "provider": "FYERS",
                "via": "callback",
                "state_jti": claims.get("jti"),
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            },
            user=None,
        )
        db.commit()
    except Exception:  # the token is already stored; do not fail the login
        logger.exception("fyers_token_audit_failed")
        db.rollback()

    expiry = (
        to_ist(record.expires_at).strftime("%d %b %Y %H:%M IST")
        if record.expires_at
        else "unknown expiry"
    )
    return _callback_page(
        "FYERS connected",
        f"The access token was stored encrypted (valid until {expiry}). You can close this tab "
        "and enable live LTP tracking in the admin settings page.",
        ok=True,
    )
