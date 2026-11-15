"""Pattern detector behaviour.

Ported from the original AVWAP scanner's ``tests/test_pattern_detector.py``.
Thresholds, ATR/body-ratio filters, lookback windows and the classification
order are the original ones; only the imports point at the ported package.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.scanner.patterns.detector import PatternDetector, small_candle_mask
from app.scanner.patterns.models import (
    PATTERN_CONSOLIDATION,
    PATTERN_HUGGING,
    PATTERN_RECLAIM,
    PATTERN_TOUCH,
    PatternConfig,
)

from .pattern_fixtures import add_indicators, make_frame


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_pattern_is_detected_with_one_to_five_candles(count):
    frame = add_indicators(make_frame(pattern_count=count))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.candle_count == count
    assert pattern.distance_pct < 0.5


def test_one_candle_touch_classification():
    frame = add_indicators(make_frame(pattern_count=1))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.touched is True
    assert pattern.pattern_type == PATTERN_TOUCH


def test_two_candle_pattern_is_hugging():
    frame = add_indicators(make_frame(pattern_count=2))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.candle_count == 2
    assert pattern.pattern_type == PATTERN_HUGGING


def test_three_candle_pattern_is_consolidation():
    frame = add_indicators(make_frame(pattern_count=3))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.pattern_type == PATTERN_CONSOLIDATION
    assert pattern.window_range_pct <= 0.01


def test_price_too_far_above_avwap_is_rejected():
    far_candle = {
        "open": 100.90,
        "high": 101.20,
        "low": 100.70,
        "close": 101.00,
        "volume": 1000.0,
    }
    frame = add_indicators(make_frame(pattern_candles=[far_candle]))
    assert PatternDetector().detect(frame) is None


def test_price_below_avwap_beyond_tolerance_is_rejected():
    below_candle = {
        "open": 99.60,
        "high": 99.80,
        "low": 99.30,
        "close": 99.50,
        "volume": 1000.0,
    }
    frame = add_indicators(make_frame(pattern_candles=[below_candle]))
    assert PatternDetector().detect(frame) is None


def test_candle_low_touching_avwap_is_touch():
    touching = {
        "open": 100.05,
        "high": 100.35,
        "low": 99.90,
        "close": 100.12,
        "volume": 1000.0,
    }
    frame = add_indicators(make_frame(pattern_candles=[touching]))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.touched is True
    assert pattern.pattern_type == PATTERN_TOUCH


def test_small_candle_body_ratio_detection():
    frame = pd.DataFrame(
        {
            "open": [100.00, 100.00],
            "high": [100.25, 100.25],
            "low": [99.95, 99.95],
            "close": [100.20, 100.05],
            "volume": [1.0, 1.0],
        }
    )
    mask = small_candle_mask(frame, max_body_ratio=0.35, max_range_atr=None)
    assert bool(mask.iloc[0]) is False
    assert bool(mask.iloc[1]) is True


def test_atr_range_cap_rejects_large_range_small_body_candle():
    frame = add_indicators(make_frame(pattern_count=1))
    frame.loc[frame.index[-1], "atr"] = 0.05
    assert PatternDetector().detect(frame) is None


def test_avwap_reclaim_is_classified():
    reclaim_candles = [
        {
            "open": 100.08,
            "high": 100.15,
            "low": 99.88,
            "close": 100.00,
            "volume": 1000.0,
        },
        {
            "open": 100.10,
            "high": 100.35,
            "low": 100.00,
            "close": 100.20,
            "volume": 1000.0,
        },
    ]
    frame = add_indicators(make_frame(pattern_candles=reclaim_candles))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    assert pattern.candle_count == 2
    assert pattern.pattern_type == PATTERN_RECLAIM


def test_missing_data_returns_none():
    detector = PatternDetector()
    assert detector.detect(pd.DataFrame()) is None
    frame = add_indicators(make_frame(pattern_count=1))
    assert PatternDetector(PatternConfig(min_candles=2)).detect(frame.iloc[-1:]) is None


def test_missing_avwap_column_raises():
    frame = add_indicators(make_frame(pattern_count=1)).drop(columns=["avwap"])
    with pytest.raises(ValueError):
        PatternDetector().detect(frame)


def test_classification_filter_can_exclude_matches():
    frame = add_indicators(make_frame(pattern_count=2))
    config = PatternConfig(allowed_patterns=(PATTERN_CONSOLIDATION,))
    assert PatternDetector(config).detect(frame) is None


def _close_relative_frame(last_close: float, session_vwap: float = 100.0) -> pd.DataFrame:
    candle = {
        "open": last_close - 0.05,
        "high": last_close + 0.15,
        "low": last_close - 0.20,
        "close": last_close,
        "volume": 1000.0,
    }
    frame = add_indicators(make_frame(pattern_candles=[candle]))
    frame["avwap"] = 100.0
    frame["session_vwap"] = session_vwap
    return frame


def test_close_above_avwap_filter_accepts_close_above():
    frame = _close_relative_frame(100.10)
    config = PatternConfig(require_close_above_avwap=True)
    assert PatternDetector(config).detect(frame) is not None


def test_close_above_avwap_filter_rejects_close_below():
    frame = _close_relative_frame(99.95)
    assert PatternDetector().detect(frame) is not None
    config = PatternConfig(require_close_above_avwap=True)
    assert PatternDetector(config).detect(frame) is None


def test_close_above_vwap_filter_accepts_and_rejects():
    config = PatternConfig(require_close_above_vwap=True)
    above = _close_relative_frame(100.10, session_vwap=99.90)
    assert PatternDetector(config).detect(above) is not None
    below = _close_relative_frame(100.10, session_vwap=100.30)
    assert PatternDetector(config).detect(below) is None


def test_both_close_filters_require_each_reference():
    frame = _close_relative_frame(100.10, session_vwap=100.30)
    config = PatternConfig(
        require_close_above_avwap=True,
        require_close_above_vwap=True,
    )
    assert PatternDetector(config).detect(frame) is None


def test_close_above_vwap_filter_requires_session_vwap_column():
    frame = _close_relative_frame(100.10).drop(columns=["session_vwap"])
    config = PatternConfig(require_close_above_vwap=True)
    with pytest.raises(ValueError):
        PatternDetector(config).detect(frame)


def _flat_candle(close: float) -> dict[str, float]:
    return {
        "open": close,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
        "volume": 1000.0,
    }


def _below_frame(previous_close: float, second_close: float | None = None) -> pd.DataFrame:
    candles: list[dict[str, float]] = []
    if second_close is not None:
        candles.append(_flat_candle(second_close))
    candles.append(_flat_candle(previous_close))
    candles.append(
        {
            "open": 100.05,
            "high": 100.30,
            "low": 99.90,
            "close": 100.10,
            "volume": 1000.0,
        }
    )
    frame = add_indicators(make_frame(pattern_candles=candles))
    frame["avwap"] = 100.0
    frame["session_vwap"] = 100.0
    return frame


def test_below_previous_avwap_filter_accepts_and_rejects():
    config = PatternConfig(below_reference="avwap", below_candle="previous")
    assert PatternDetector(config).detect(_below_frame(99.80)) is not None
    assert PatternDetector(config).detect(_below_frame(100.20)) is None
    assert PatternDetector().detect(_below_frame(100.20)) is not None


def test_below_second_previous_lookback_options():
    frame = _below_frame(previous_close=100.20, second_close=99.80)
    second = PatternConfig(below_reference="avwap", below_candle="second_previous")
    previous = PatternConfig(below_reference="avwap", below_candle="previous")
    either = PatternConfig(below_reference="avwap", below_candle="either")
    assert PatternDetector(second).detect(frame) is not None
    assert PatternDetector(previous).detect(frame) is None
    assert PatternDetector(either).detect(frame) is not None


def test_below_vwap_reference_distinguishes_lines():
    frame = _below_frame(99.95)
    frame["avwap"] = 99.90
    frame["session_vwap"] = 100.0
    vwap = PatternConfig(below_reference="vwap", below_candle="previous")
    avwap = PatternConfig(below_reference="avwap", below_candle="previous")
    either = PatternConfig(below_reference="either", below_candle="previous")
    assert PatternDetector(vwap).detect(frame) is not None
    assert PatternDetector(avwap).detect(frame) is None
    assert PatternDetector(either).detect(frame) is not None


def test_below_vwap_filter_requires_session_vwap_column():
    frame = _below_frame(99.80).drop(columns=["session_vwap"])
    config = PatternConfig(below_reference="vwap", below_candle="previous")
    with pytest.raises(ValueError):
        PatternDetector(config).detect(frame)


def test_invalid_below_options_raise():
    with pytest.raises(ValueError):
        PatternConfig(below_reference="bogus")
    with pytest.raises(ValueError):
        PatternConfig(below_candle="bogus")


def test_config_rejects_unknown_pattern_type_and_bad_bounds():
    with pytest.raises(ValueError):
        PatternConfig(allowed_patterns=("NOT A PATTERN",))
    with pytest.raises(ValueError):
        PatternConfig(min_candles=0)
    with pytest.raises(ValueError):
        PatternConfig(min_candles=3, max_candles=2)
    with pytest.raises(ValueError):
        PatternConfig(max_body_ratio=1.5)
    with pytest.raises(ValueError):
        PatternConfig(max_candle_range_atr=0)


def test_config_defaults_match_original_thresholds():
    config = PatternConfig().to_dict()
    assert config["max_close_above_pct"] == 0.005
    assert config["max_close_below_pct"] == 0.002
    assert config["max_low_below_pct"] == 0.003
    assert config["max_body_ratio"] == 0.35
    assert config["min_candles"] == 1
    assert config["max_candles"] == 5
    assert config["max_window_range_pct"] == 0.02
    assert config["max_candle_range_atr"] == 2.0
    assert config["touch_tolerance_pct"] == 0.001
    assert config["consolidation_min_candles"] == 3
    assert config["consolidation_range_pct"] == 0.01
    assert config["hugging_min_candles"] == 2
    # Optional filters stay off by default, exactly as in the original.
    assert config["require_close_above_avwap"] is False
    assert config["require_close_above_vwap"] is False
    assert config["below_reference"] == "off"


def test_detected_pattern_metadata_has_no_confidence_score():
    frame = add_indicators(make_frame(pattern_count=2))
    pattern = PatternDetector().detect(frame)
    assert pattern is not None
    metadata = pattern.to_metadata()
    assert metadata["pattern_type"] == PATTERN_HUGGING
    assert metadata["candle_count"] == 2
    assert metadata["start_idx"] == len(frame) - 2
    assert metadata["end_idx"] == len(frame) - 1
    assert metadata["pattern_end"] is not None
    assert metadata["anchor_timestamp"] is not None
    assert "confidence" not in metadata
    assert "score" not in metadata
    assert set(metadata) == {
        "pattern_type",
        "candle_count",
        "start_idx",
        "end_idx",
        "pattern_start",
        "pattern_end",
        "last_price",
        "avwap",
        "distance_pct",
        "avg_body_ratio",
        "max_body_ratio",
        "window_range_pct",
        "touched",
        "anchor_timestamp",
        "latest_atr",
    }
