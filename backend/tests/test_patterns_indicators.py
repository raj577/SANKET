"""AVWAP / session VWAP / ATR and candle-completion behaviour.

The AVWAP cases are ported from the original AVWAP scanner's
``tests/test_avwap.py``. ATR and normalization cases cover the ported
``app/scanner/patterns`` helpers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.scanner.patterns.candles import (
    drop_incomplete_candles,
    normalize_candles,
    resolution_minutes,
)
from app.scanner.patterns.indicators import (
    compute_atr,
    compute_contract_avwap,
    compute_session_vwap,
)

TZ = "Asia/Kolkata"


def _candles(prices, volumes=None, timestamps=None):
    volumes = volumes or [100.0] * len(prices)
    if timestamps is None:
        timestamps = pd.date_range(
            "2026-11-02 09:15", periods=len(prices), freq="h", tz=TZ
        )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": volumes,
        }
    )


# --------------------------------------------------------------- AVWAP / VWAP


def test_avwap_known_values():
    frame = _candles([10.0, 20.0], volumes=[100.0, 300.0])
    avwap = compute_contract_avwap(frame)
    assert avwap.iloc[0] == pytest.approx(10.0)
    assert avwap.iloc[1] == pytest.approx((10 * 100 + 20 * 300) / 400)


def test_avwap_uses_typical_price():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-11-02 09:15", periods=1, freq="h", tz=TZ),
            "open": [9.0],
            "high": [12.0],
            "low": [8.0],
            "close": [10.0],
            "volume": [50.0],
        }
    )
    avwap = compute_contract_avwap(frame)
    assert avwap.iloc[0] == pytest.approx((12.0 + 8.0 + 10.0) / 3.0)


def test_contract_start_avwap_does_not_reset_daily():
    timestamps = pd.to_datetime(
        [
            "2026-11-02 09:15",
            "2026-11-02 10:15",
            "2026-11-03 09:15",
            "2026-11-03 10:15",
        ]
    ).tz_localize(TZ)
    frame = _candles([100.0, 100.0, 200.0, 200.0], timestamps=timestamps)

    contract_avwap = compute_contract_avwap(frame)
    session_vwap = compute_session_vwap(frame, TZ)

    assert contract_avwap.iloc[2] == pytest.approx(400.0 / 3.0)
    assert session_vwap.iloc[2] == pytest.approx(200.0)
    assert contract_avwap.iloc[2] != session_vwap.iloc[2]
    assert contract_avwap.iloc[3] == pytest.approx(150.0)


def test_avwap_anchor_index_skips_earlier_rows():
    frame = _candles([10.0, 20.0, 30.0, 40.0])
    avwap = compute_contract_avwap(frame, anchor_index=2)
    assert pd.isna(avwap.iloc[0])
    assert pd.isna(avwap.iloc[1])
    assert avwap.iloc[2] == pytest.approx(30.0)
    assert avwap.iloc[3] == pytest.approx(35.0)


def test_zero_volume_rows_do_not_change_avwap():
    frame = _candles([100.0, 110.0, 120.0], volumes=[0.0, 10.0, 10.0])
    avwap = compute_contract_avwap(frame)
    assert pd.isna(avwap.iloc[0])
    assert avwap.iloc[1] == pytest.approx(110.0)
    assert avwap.iloc[2] == pytest.approx(115.0)


def test_session_vwap_resets_each_day_while_avwap_does_not():
    timestamps = pd.to_datetime(
        [
            "2026-11-02 09:15",
            "2026-11-02 10:15",
            "2026-11-03 09:15",
            "2026-11-03 10:15",
        ]
    ).tz_localize(TZ)
    frame = _candles([100.0, 100.0, 200.0, 200.0], timestamps=timestamps)
    contract_avwap = compute_contract_avwap(frame)
    session_vwap = compute_session_vwap(frame, TZ)

    assert session_vwap.iloc[0] == pytest.approx(100.0)
    assert session_vwap.iloc[1] == pytest.approx(100.0)
    assert session_vwap.iloc[2] == pytest.approx(200.0)
    assert contract_avwap.iloc[2] == pytest.approx(400.0 / 3.0)


def test_avwap_requires_ohlcv_columns():
    frame = _candles([10.0]).drop(columns=["volume"])
    with pytest.raises(ValueError):
        compute_contract_avwap(frame)


def test_avwap_anchor_outside_data_raises():
    frame = _candles([10.0, 20.0])
    with pytest.raises(ValueError):
        compute_contract_avwap(frame, anchor_index=5)


def test_empty_avwap_is_empty_series():
    frame = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    result = compute_contract_avwap(frame)
    assert result.empty


# ------------------------------------------------------------------------ ATR


def test_atr_is_nan_until_period_candles_exist():
    frame = _candles([100.0] * 20)
    atr = compute_atr(frame, period=14)
    assert atr.iloc[:13].isna().all()
    assert atr.iloc[13:].notna().all()


def test_atr_matches_wilder_average_on_constant_ranges():
    frame = _candles([100.0] * 20)
    frame["high"] = frame["close"] + 1.0
    frame["low"] = frame["close"] - 1.0
    atr = compute_atr(frame, period=14)
    # First true range is high - low = 2.0; all later ranges equal 2.0, so the
    # Wilder average stays at 2.0.
    assert atr.iloc[-1] == pytest.approx(2.0)


def test_atr_rejects_invalid_period():
    frame = _candles([100.0])
    with pytest.raises(ValueError):
        compute_atr(frame, period=0)


# ------------------------------------------------------------ candle handling


def test_drop_incomplete_candles_removes_forming_bar():
    now = pd.Timestamp("2026-11-04 09:15", tz=TZ)
    timestamps = pd.to_datetime(
        ["2026-11-04 07:15", "2026-11-04 08:15", "2026-11-04 09:15"]
    ).tz_localize(TZ)
    frame = _candles([100.0, 101.0, 102.0], timestamps=timestamps)

    completed = drop_incomplete_candles(frame, "60", now=now, timezone=TZ)
    assert len(completed) == 2
    assert completed["timestamp"].iloc[-1] == timestamps[1]


def test_final_short_session_candle_is_complete_after_market_close():
    timestamps = pd.to_datetime(
        ["2026-11-04 14:15", "2026-11-04 15:15"]
    ).tz_localize(TZ)
    frame = _candles([100.0, 101.0], timestamps=timestamps)

    before_close = drop_incomplete_candles(
        frame, "60", now=pd.Timestamp("2026-11-04 15:20", tz=TZ), timezone=TZ
    )
    after_close = drop_incomplete_candles(
        frame, "60", now=pd.Timestamp("2026-11-04 15:35", tz=TZ), timezone=TZ
    )
    assert len(before_close) == 1
    assert len(after_close) == 2


def test_daily_resolution_completes_next_day():
    timestamps = pd.to_datetime(["2026-11-03", "2026-11-04"]).tz_localize(TZ)
    frame = _candles([100.0, 101.0], timestamps=timestamps)
    completed = drop_incomplete_candles(
        frame, "D", now=pd.Timestamp("2026-11-04 10:00", tz=TZ), timezone=TZ
    )
    assert len(completed) == 1
    assert completed["timestamp"].iloc[0] == timestamps[0]


def test_drop_incomplete_candles_handles_empty_frame():
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    assert drop_incomplete_candles(empty, "60").empty


def test_resolution_minutes_accepts_intraday_and_daily():
    assert resolution_minutes("5") == 5
    assert resolution_minutes("60") == 60
    assert resolution_minutes("15m") == 15
    assert resolution_minutes("D") is None
    assert resolution_minutes("1D") is None
    with pytest.raises(ValueError):
        resolution_minutes("weekly")
    with pytest.raises(ValueError):
        resolution_minutes("0")


# ----------------------------------------------------------- normalization


def test_normalize_candles_parses_epoch_seconds_rows():
    rows = [
        [1730610900, 100.0, 101.0, 99.5, 100.5, 1234.0],
        [1730614500, 100.5, 101.5, 100.0, 101.0, 4321.0],
    ]
    frame = normalize_candles(rows, TZ)
    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert str(frame["timestamp"].dt.tz) == TZ
    assert frame["timestamp"].is_monotonic_increasing


def test_normalize_candles_sorts_deduplicates_and_drops_invalid_rows():
    rows = [
        [1730614500, 100.5, 101.5, 100.0, 101.0, 10.0],
        [1730610900, 100.0, 101.0, 99.5, 100.5, 10.0],
        # Duplicate timestamp: last one wins.
        [1730614500, 200.0, 201.0, 199.0, 200.5, 20.0],
        # high < low -> invalid, dropped.
        [1730618100, 100.0, 99.0, 101.0, 100.0, 10.0],
        # Missing close -> dropped.
        [1730621700, 100.0, 101.0, 99.0, None, 10.0],
    ]
    frame = normalize_candles(rows, TZ)
    assert len(frame) == 2
    assert frame["close"].iloc[1] == pytest.approx(200.5)


def test_normalize_candles_handles_empty_input():
    frame = normalize_candles([], TZ)
    assert frame.empty
    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_normalize_candles_fills_missing_volume_with_zero():
    rows = [[1730610900, 100.0, 101.0, 99.5, 100.5, None]]
    frame = normalize_candles(rows, TZ)
    assert frame["volume"].iloc[0] == 0.0
    assert not frame["volume"].isna().any()


def test_normalize_candles_accepts_dataframe_with_indexed_timestamp():
    index = pd.to_datetime(["2026-11-02 09:15", "2026-11-02 10:15"]).tz_localize(TZ)
    raw = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 20.0],
        },
        index=index,
    )
    raw.index.name = "timestamp"
    frame = normalize_candles(raw, TZ)
    assert len(frame) == 2
    assert "timestamp" in frame.columns


def test_normalize_candles_millisecond_epochs_are_detected():
    rows = [
        [1730610900000, 100.0, 101.0, 99.5, 100.5, 10.0],
        [1730614500000, 100.5, 101.5, 100.0, 101.0, 10.0],
    ]
    frame = normalize_candles(rows, TZ)
    assert len(frame) == 2
    assert np.isfinite(frame["close"]).all()
