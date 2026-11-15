"""Candle normalization and completion helpers.

Ported from the original AVWAP scanner (``data/historical_data.py``) without
the FYERS transport, cache or orchestration layers.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class NoMarketDataError(RuntimeError):
    """No usable candles were returned for a contract."""


def _epoch_unit(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce")
    median = float(numeric.dropna().abs().median()) if numeric.notna().any() else 0.0
    if median >= 1e15:
        return "us"
    if median >= 1e11:
        return "ms"
    return "s"


def normalize_candles(
    raw: Iterable[Iterable[Any]] | pd.DataFrame,
    timezone: str = "Asia/Kolkata",
) -> pd.DataFrame:
    """Convert raw FYERS rows to a clean, sorted, tz-aware OHLCV DataFrame."""

    if isinstance(raw, pd.DataFrame):
        frame = raw.copy()
        if "timestamp" not in frame.columns:
            if frame.index.name == "timestamp":
                frame = frame.reset_index()
            else:
                raise ValueError("Candle DataFrame has no timestamp column")
    else:
        rows = [list(row)[:6] for row in raw if row is not None and len(row) >= 6]
        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        frame = pd.DataFrame(rows, columns=OHLCV_COLUMNS)

    if frame.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    source_timestamps = frame["timestamp"]
    if is_datetime64_any_dtype(source_timestamps):
        parsed = pd.to_datetime(source_timestamps, errors="coerce", utc=True)
    elif is_numeric_dtype(source_timestamps):
        unit = _epoch_unit(source_timestamps)
        parsed = pd.to_datetime(
            pd.to_numeric(source_timestamps, errors="coerce"),
            unit=unit,
            utc=True,
            errors="coerce",
        )
    else:
        numeric = pd.to_numeric(source_timestamps, errors="coerce")
        looks_numeric = numeric.notna().mean() >= 0.8
        if looks_numeric and abs(float(numeric.dropna().median())) > 1e8:
            unit = _epoch_unit(numeric)
            parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        else:
            parsed = pd.to_datetime(source_timestamps, errors="coerce", utc=True)
    frame["timestamp"] = pd.Series(parsed, index=frame.index).dt.tz_convert(timezone)

    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame["volume"] = frame["volume"].fillna(0.0).clip(lower=0.0)
    frame = frame.loc[frame["high"] >= frame["low"]]
    frame = (
        frame.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    return frame[OHLCV_COLUMNS]


def resolution_minutes(resolution: str) -> int | None:
    """Return interval minutes for intraday resolutions, or None for daily."""
    text = str(resolution).strip().upper()
    if text in {"D", "1D", "DAY", "DAILY"}:
        return None
    match = re.fullmatch(r"(\d+)\s*(?:MIN|M)?", text)
    if match:
        minutes = int(match.group(1))
        if minutes <= 0:
            raise ValueError(f"Invalid resolution: {resolution}")
        return minutes
    raise ValueError(f"Unsupported resolution: {resolution}")


def drop_incomplete_candles(
    candles: pd.DataFrame,
    resolution: str,
    now: pd.Timestamp | datetime | None = None,
    timezone: str = "Asia/Kolkata",
) -> pd.DataFrame:
    """Drop the currently forming candle so detection uses completed bars only."""

    if candles.empty:
        return candles.copy()

    if now is None:
        now_ts = pd.Timestamp.now(tz=timezone)
    else:
        now_ts = pd.Timestamp(now)
        if now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize(timezone)
        else:
            now_ts = now_ts.tz_convert(timezone)

    timestamps = pd.to_datetime(candles["timestamp"])
    if not isinstance(timestamps.dtype, pd.DatetimeTZDtype):
        timestamps = timestamps.dt.tz_localize(timezone)
    else:
        timestamps = timestamps.dt.tz_convert(timezone)

    minutes = resolution_minutes(resolution)
    if minutes is None:
        expected_end = timestamps + pd.Timedelta(1, "D")
    else:
        expected_end = timestamps + pd.Timedelta(minutes, "m")
        # NSE equity/F&O sessions close at 15:30 IST. A final short candle
        # (for example 15:15-15:30) is complete at the session close, not one
        # full resolution later.
        session_close = timestamps.dt.normalize() + pd.Timedelta(15 * 60 + 30, "m")
        expected_end = expected_end.where(expected_end <= session_close, session_close)
    completed = expected_end <= now_ts
    return candles.loc[completed].reset_index(drop=True)


def iso_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
