"""Synthetic, deterministic candle fixtures for the pattern-scanner tests.

Ported from the original AVWAP scanner's ``tests/helpers.py`` so the detector
assertions keep using the same baseline/small-candle shapes. Timestamps are
fixed (instead of relative to ``now``) so every test is deterministic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd

from app.scanner.patterns.indicators import (
    compute_atr,
    compute_contract_avwap,
    compute_session_vwap,
)
from app.scanner.patterns.models import Instrument

TZ = "Asia/Kolkata"
DEFAULT_START = pd.Timestamp("2026-11-02 09:15", tz=TZ)

BASELINE_CANDLE = {
    "open": 99.5,
    "high": 100.8,
    "low": 99.2,
    "close": 100.5,
    "volume": 1000.0,
}

SMALL_PATTERN_CANDLE = {
    "open": 100.05,
    "high": 100.30,
    "low": 99.90,
    "close": 100.10,
    "volume": 1000.0,
}


def make_frame(
    pattern_count: int = 0,
    pattern_candles: Iterable[dict[str, float]] | None = None,
    baseline_count: int = 40,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Build baseline candles followed by a small-candle pattern cluster."""
    patterns = (
        list(pattern_candles)
        if pattern_candles is not None
        else [dict(SMALL_PATTERN_CANDLE) for _ in range(pattern_count)]
    )
    total = baseline_count + len(patterns)
    start = start or DEFAULT_START
    timestamps = pd.date_range(start, periods=total, freq="60min")

    rows = []
    for offset in range(total):
        candle = (
            dict(BASELINE_CANDLE)
            if offset < baseline_count
            else patterns[offset - baseline_count]
        )
        rows.append(
            {
                "timestamp": timestamps[offset],
                **candle,
            }
        )
    frame = pd.DataFrame(rows)
    frame["volume"] = frame["volume"].astype("float64")
    return frame


def add_indicators(frame: pd.DataFrame, timezone: str = TZ) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["avwap"] = compute_contract_avwap(enriched)
    enriched["session_vwap"] = compute_session_vwap(enriched, timezone)
    enriched["atr"] = compute_atr(enriched, period=14)
    return enriched


def make_instrument(
    symbol: str = "NSE:TEST26NOVFUT",
    underlying: str = "TEST",
    expiry: object = "auto",
) -> Instrument:
    if expiry == "auto":
        expiry = date.today() + timedelta(days=20)
    return Instrument(
        symbol=symbol,
        underlying=underlying,
        expiry=expiry,
        description=f"{underlying} FUT",
        lot_size=1.0,
        is_index=False,
    )


class FakeHistoryService:
    """Stand-in for ``PatternHistoryService`` with no network access."""

    def __init__(
        self,
        frame: pd.DataFrame | None = None,
        *,
        frames: dict[str, pd.DataFrame] | None = None,
        failures: dict[str, str] | None = None,
    ) -> None:
        self.frame = frame
        self.frames = dict(frames or {})
        self.failures = dict(failures or {})
        self.calls: list[dict[str, object]] = []

    def fetch(self, instrument: Instrument, resolution: str | None = None, end_date=None):
        self.calls.append(
            {
                "symbol": instrument.symbol,
                "resolution": resolution,
                "end_date": end_date,
            }
        )
        symbol = instrument.symbol
        if symbol in self.failures:
            raise RuntimeError(self.failures[symbol])
        frame = self.frames.get(symbol, self.frame)
        if frame is None:
            raise RuntimeError(f"No data for {symbol}")
        return frame.copy()


def ist(*parts: int) -> pd.Timestamp:
    """Build a tz-aware IST timestamp from ``(y, m, d, h, min)``."""
    return pd.Timestamp(datetime(*parts), tz=TZ)
