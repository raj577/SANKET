"""Periodic FYERS LTP tracker for active published signals.

The worker only ever stores prices that FYERS actually returned. Missing
quotes, expired tokens and network errors leave the last observed price (or
UNKNOWN freshness) untouched.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutils import utcnow
from app.db.session import get_sessionmaker
from app.market_data.fyers_client import FyersClient, FyersError
from app.market_data.kotak_client import KotakError
from app.market_data.price_tracker import apply_price_tick
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.services import settings_service
from app.services.ws_manager import broadcast_signal_event, hub

logger = get_logger(__name__)

INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:NIFTYMIDCAP150-INDEX",
}

QUOTE_CHUNK_SIZE = 50


def to_fyers_symbol(symbol: str) -> str:
    name = symbol.strip().upper()
    if name in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[name]
    return f"NSE:{name}-EQ"


def identity_symbol(symbol: str) -> str:
    """Kotak quotes use the plain NSE symbol, not a ``NSE:...`` string."""
    return symbol.strip().upper()


def make_client(provider: str):
    if provider == "kotak":
        from app.market_data.kotak_client import KotakClient

        return KotakClient()
    return FyersClient()


def symbol_mapper_for(provider: str):
    return identity_symbol if provider == "kotak" else to_fyers_symbol


def _chunks(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def fetch_ltps(client: FyersClient, symbols: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for chunk in _chunks(symbols, QUOTE_CHUNK_SIZE):
        prices.update(client.ltp_map(chunk))
    return prices


def run_once(
    db: Session,
    client: FyersClient,
    *,
    now: datetime | None = None,
    tracking_enabled: bool | None = None,
    symbol_mapper=to_fyers_symbol,
) -> dict:
    market_settings = settings_service.get_value(db, "market_data")
    if tracking_enabled is None:
        tracking_enabled = bool(market_settings.get("tracking_enabled", False))
    if not tracking_enabled:
        return {"updated": 0, "quotes": {}, "events": [], "skipped": "tracking_disabled"}

    signals = list(
        db.scalars(
            select(PublishedSignal).where(
                PublishedSignal.status == SignalStatus.ACTIVE.value
            )
        ).all()
    )
    if not signals:
        return {"updated": 0, "quotes": {}, "events": []}

    keys = sorted({symbol_mapper(signal.symbol) for signal in signals})
    try:
        prices = fetch_ltps(client, keys)
    except (FyersError, KotakError) as exc:
        logger.warning("market_data_quote_failed", extra={"error": str(exc)})
        return {"updated": 0, "quotes": {}, "events": [], "error": str(exc)}

    observed_at = now or utcnow()
    persist_interval = int(
        market_settings.get(
            "persist_interval_seconds", get_settings().price_persist_interval_seconds
        )
    )
    updated = 0
    events: list[dict] = []
    quoted: dict[str, float] = {}

    for signal in signals:
        key = symbol_mapper(signal.symbol)
        ltp = prices.get(key)
        if ltp is None:
            continue
        quoted[signal.symbol] = ltp
        result = apply_price_tick(
            db,
            signal,
            Decimal(str(ltp)),
            captured_at=observed_at,
            persist_interval_seconds=persist_interval,
        )
        if result["changed"]:
            updated += 1
        if result["event"]:
            events.append(
                {
                    "signal_id": str(signal.id),
                    "symbol": signal.symbol,
                    "event": result["event"],
                    "ltp": ltp,
                }
            )
    return {"updated": updated, "quotes": quoted, "events": events}


_warned_not_configured = False


def _poll_once() -> dict:
    settings = get_settings()
    provider = (settings.market_data_provider or "fyers").lower()
    client = make_client(provider)
    if not client.configured:
        global _warned_not_configured
        if not _warned_not_configured:
            logger.warning(
                "price_tracker_not_configured",
                extra={
                    "provider": provider,
                    "hint": "Set the provider credentials in backend/.env",
                },
            )
            _warned_not_configured = True
        return {
            "updated": 0,
            "quotes": {},
            "events": [],
            "skipped": f"{provider}_not_configured",
        }

    session = get_sessionmaker()()
    try:
        return run_once(
            session,
            client,
            symbol_mapper=symbol_mapper_for(provider),
        )
    finally:
        session.close()
        client.close()


async def run_forever() -> None:
    settings = get_settings()
    interval = max(int(settings.tracking_poll_seconds), 5)
    logger.info("price_tracker_started", extra={"interval_seconds": interval})
    try:
        while True:
            try:
                result = await asyncio.to_thread(_poll_once)
                if result.get("quotes"):
                    await hub.broadcast(
                        "market",
                        {
                            "event": "prices",
                            "data": result["quotes"],
                            "observed_at": utcnow().isoformat(),
                        },
                    )
                for event in result.get("events", []):
                    await broadcast_signal_event("signal_" + event["event"].lower(), event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the worker must keep running
                logger.exception("price_tracker_cycle_failed", extra={"error": str(exc)})
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("price_tracker_stopped")
        raise


def start_worker() -> asyncio.Task:
    settings = get_settings()
    if (settings.market_data_provider or "").lower() == "kotak":
        from app.workers.kotak_stream_worker import run_forever as kotak_run_forever

        return asyncio.create_task(kotak_run_forever(), name="kotak-price-tracker")
    return asyncio.create_task(run_forever(), name="price-tracker")


async def stop_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
