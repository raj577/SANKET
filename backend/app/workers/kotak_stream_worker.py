"""Kotak Neo SFeed websocket tracker for active published signals.

Ticks are applied through the same price thresholders used by the REST
poller, so a target or stop-loss crossing closes the signal exactly once and
broadcasts the event to the websocket clients. If streaming credentials are
missing or the transport is configured as ``rest``, the worker falls back to
REST quote polling.
"""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutils import utcnow
from app.db.session import get_sessionmaker
from app.market_data.kotak_client import KotakClient, normalize_segment, normalize_symbol
from app.market_data.price_tracker import apply_price_tick, evaluate_threshold
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.services import settings_service
from app.services.ws_manager import broadcast_signal_event, hub

logger = get_logger(__name__)

ACTIVE = SignalStatus.ACTIVE.value


def _load_active_context() -> tuple[list[str], dict[str, list[tuple]]]:
    """Return active symbols and their direction/target/stop thresholds."""
    session = get_sessionmaker()()
    try:
        rows = session.execute(
            select(
                PublishedSignal.symbol,
                PublishedSignal.direction,
                PublishedSignal.target_price,
                PublishedSignal.stop_loss,
            ).where(PublishedSignal.status == ACTIVE)
        ).all()
        levels: dict[str, list[tuple]] = {}
        for symbol, direction, target, stop_loss in rows:
            levels.setdefault(normalize_symbol(symbol), []).append(
                (direction, target, stop_loss)
            )
        return sorted(levels), levels
    finally:
        session.close()


def _crosses_threshold(symbol: str, ltp: float, levels: dict[str, list[tuple]]) -> bool:
    value = Decimal(str(ltp))
    return any(
        evaluate_threshold(direction, value, target, stop_loss) is not None
        for direction, target, stop_loss in levels.get(symbol, [])
    )


def _record_tick(symbol: str, ltp: float) -> list[dict]:
    """Apply one observed LTP to every active signal for ``symbol``."""
    session = get_sessionmaker()()
    try:
        market_settings = settings_service.get_value(session, "market_data")
        if not bool(market_settings.get("tracking_enabled", False)):
            return []
        persist_interval = int(
            market_settings.get(
                "persist_interval_seconds",
                get_settings().price_persist_interval_seconds,
            )
        )
        signals = list(
            session.scalars(
                select(PublishedSignal).where(
                    PublishedSignal.status == ACTIVE,
                    func.upper(PublishedSignal.symbol) == normalize_symbol(symbol),
                )
            ).all()
        )
        events: list[dict] = []
        for signal in signals:
            result = apply_price_tick(
                session,
                signal,
                Decimal(str(ltp)),
                persist_interval_seconds=persist_interval,
            )
            if result.get("event"):
                events.append(
                    {
                        "signal_id": str(signal.id),
                        "symbol": signal.symbol,
                        "event": result["event"],
                        "ltp": float(ltp),
                    }
                )
        return events
    finally:
        session.close()


async def _broadcast(result: dict) -> None:
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


async def _rest_loop(client: KotakClient) -> None:
    """REST polling fallback (quotes only need the consumer key)."""
    from app.workers.price_tracker_worker import identity_symbol, run_once

    settings = get_settings()
    interval = max(int(settings.tracking_poll_seconds), 5)
    while True:
        session = get_sessionmaker()()
        try:
            result = await asyncio.to_thread(
                run_once, session, client, symbol_mapper=identity_symbol
            )
        finally:
            session.close()
        await _broadcast(result)
        await asyncio.sleep(interval)


async def _stream_session(client: KotakClient) -> None:
    settings = get_settings()
    sdk = await asyncio.to_thread(client.authenticated_sdk)

    from neo_api_client.websocket.feed import SFeedIndex, SFeedScrip, WsToken

    throttle = max(float(settings.market_data_tick_throttle_seconds), 0.25)
    refresh_seconds = max(int(settings.kotak_stream_refresh_seconds), 15)

    async with sdk.create_websocket() as ws:
        subscribed: set[tuple[str, str]] = set()
        token_symbols: dict[tuple[str, str], str] = {}
        levels: dict[str, list[tuple]] = {}
        last_applied: dict[str, float] = {}

        async def refresh_subscriptions() -> None:
            while True:
                symbols, active_levels = await asyncio.to_thread(_load_active_context)
                levels.clear()
                levels.update(active_levels)
                token_map = await asyncio.to_thread(client.active_token_map, symbols)
                token_symbols.clear()
                token_symbols.update(token_map)
                new_tokens = [token for token in token_map if token not in subscribed]
                if new_tokens:
                    await ws.subscribe_scrips(
                        [WsToken(segment, token) for segment, token in new_tokens]
                    )
                    subscribed.update(new_tokens)
                    logger.info(
                        "kotak_stream_subscribed",
                        extra={"count": len(subscribed)},
                    )
                await asyncio.sleep(refresh_seconds)

        async def consume() -> None:
            seen: set[str] = set()
            unresolved: set[tuple[str, str]] = set()
            async for message in ws:
                if not isinstance(message, (SFeedScrip, SFeedIndex)):
                    continue
                ltp = getattr(message, "last_traded_price", None)
                if ltp is None:
                    continue
                segment = normalize_segment(getattr(message, "exchange_segment", ""))
                token = str(getattr(message, "instrument_token", ""))
                symbol = token_symbols.get((segment, token))
                if symbol is None:
                    label = getattr(message, "trading_symbol", None) or getattr(
                        message, "name", None
                    )
                    symbol = client.symbol_for_message(segment, token, label)
                if not symbol:
                    if (segment, token) not in unresolved:
                        unresolved.add((segment, token))
                        logger.warning(
                            "kotak_tick_unresolved",
                            extra={"segment": segment, "token": token},
                        )
                    continue

                if symbol not in seen:
                    seen.add(symbol)
                    logger.info(
                        "kotak_tick_received",
                        extra={"symbol": symbol, "ltp": float(ltp)},
                    )

                now = time.monotonic()
                force = _crosses_threshold(symbol, float(ltp), levels)
                if not force and now - last_applied.get(symbol, 0.0) < throttle:
                    continue
                last_applied[symbol] = now

                try:
                    events = await asyncio.to_thread(_record_tick, symbol, float(ltp))
                except Exception as exc:  # noqa: BLE001 - keep the feed alive
                    logger.exception(
                        "kotak_tick_apply_failed",
                        extra={"symbol": symbol, "error": str(exc)},
                    )
                    continue
                await _broadcast({"quotes": {symbol: float(ltp)}, "events": events})

        tasks = [
            asyncio.create_task(refresh_subscriptions(), name="kotak-subscriptions"),
            asyncio.create_task(consume(), name="kotak-feed"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            error = task.exception()
            if error is not None:
                raise error


_warned_not_configured = False


async def run_forever() -> None:
    settings = get_settings()
    logger.info(
        "kotak_tracker_started",
        extra={
            "transport": settings.market_data_transport,
            "poll_interval_seconds": settings.tracking_poll_seconds,
        },
    )
    while True:
        try:
            client = KotakClient()
            if not client.configured:
                global _warned_not_configured
                if not _warned_not_configured:
                    logger.warning(
                        "kotak_tracker_not_configured",
                        extra={"hint": "Set KOTAK_CONSUMER_KEY in backend/.env"},
                    )
                    _warned_not_configured = True
                await asyncio.sleep(60)
                continue

            if (
                settings.market_data_transport != "websocket"
                or not client.stream_ready
            ):
                if settings.market_data_transport == "websocket":
                    logger.warning(
                        "kotak_stream_credentials_incomplete",
                        extra={
                            "hint": "Falling back to REST quotes; set mobile, UCC, MPIN and TOTP secret for streaming"
                        },
                    )
                await _rest_loop(client)
                continue

            await _stream_session(client)
            logger.warning("kotak_stream_ended", extra={"hint": "reconnecting"})
        except asyncio.CancelledError:
            logger.info("kotak_tracker_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - the worker must keep running
            logger.exception("kotak_tracker_cycle_failed", extra={"error": str(exc)})
        await asyncio.sleep(max(int(settings.tracking_poll_seconds), 5))
