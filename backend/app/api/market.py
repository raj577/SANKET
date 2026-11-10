"""Market-data endpoints.

Prices are only reported when they were actually observed. A configured but
unpolled symbol returns no price rather than a fabricated one.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, require_admin
from app.core.exceptions import NotFoundError
from app.core.timeutils import utcnow
from app.db.session import get_db
from app.market_data import fyers_auth
from app.market_data.fyers_client import FyersTokenStore
from app.market_data.provider import provider_status
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.models.user import User
from app.schemas.admin import PriceOut
from app.schemas.serializers import price_freshness
from app.services import audit_service, settings_service

router = APIRouter(prefix="/market", tags=["market"])


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


@router.get("/fyers/login-url")
def fyers_login_url(_: User = Depends(require_admin)) -> dict:
    return {"url": fyers_auth.build_login_url()}


@router.post("/fyers/exchange")
def exchange_fyers_code(
    code: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    token = fyers_auth.exchange_auth_code(code)
    FyersTokenStore().save(token)
    audit_service.record(
        db,
        action="FYERS_TOKEN_UPDATED",
        entity_type="market_data",
        details={"provider": "FYERS"},
        user=admin,
    )
    db.commit()
    return {"detail": "FYERS access token stored", "updated_at": utcnow()}


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


@router.get("/fyers/callback", response_class=HTMLResponse, include_in_schema=False)
def fyers_callback(
    code: str | None = None,
    auth_code: str | None = None,
    state: str | None = None,  # noqa: ARG001 - FYERS echoes the login state
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """OAuth redirect target registered with FYERS.

    Exchanges the one-time auth code server-side and stores the access token.
    The token is never returned to the browser; close the tab afterwards and
    enable tracking from the admin settings page.
    """
    supplied = code or auth_code
    if not supplied:
        return _callback_page(
            "FYERS login failed",
            "No authorization code was returned. Start again from the admin panel.",
            ok=False,
        )
    try:
        token = fyers_auth.exchange_auth_code(supplied)
    except Exception as exc:  # noqa: BLE001 - show a safe message, log the cause
        return _callback_page(
            "FYERS login failed",
            f"The authorization code could not be exchanged: {exc}",
            ok=False,
        )
    FyersTokenStore().save(token)
    audit_service.record(
        db,
        action="FYERS_TOKEN_UPDATED",
        entity_type="market_data",
        details={"provider": "FYERS", "via": "callback"},
        user=None,
    )
    db.commit()
    return _callback_page(
        "FYERS connected",
        "The access token was stored. You can close this tab and enable "
        "live LTP tracking in the admin settings page.",
        ok=True,
    )
