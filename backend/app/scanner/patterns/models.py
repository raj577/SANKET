"""Domain models shared by the AVWAP pattern scanner.

Ported from the original AVWAP scanner (``scanner/models.py``). The pattern
constants, thresholds and validation rules are unchanged. Additions are
limited to JSON helpers used for persistence and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

PATTERN_TOUCH = "AVWAP TOUCH"
PATTERN_HUGGING = "AVWAP HUGGING"
PATTERN_CONSOLIDATION = "AVWAP CONSOLIDATION"
PATTERN_RECLAIM = "AVWAP RECLAIM"

PATTERN_TYPES: tuple[str, ...] = (
    PATTERN_TOUCH,
    PATTERN_HUGGING,
    PATTERN_CONSOLIDATION,
    PATTERN_RECLAIM,
)

BELOW_REFERENCES: tuple[str, ...] = ("off", "avwap", "vwap", "either")
BELOW_CANDLES: tuple[str, ...] = ("previous", "second_previous", "either")

PATTERN_SCANNER_VERSION = "avwap-pattern-1.0.0"

# Per-instrument states shown in the admin progress list.
OUTCOME_PENDING = "PENDING"
OUTCOME_SCANNING = "SCANNING"
OUTCOME_MATCHED = "MATCHED"
OUTCOME_NO_PATTERN = "NO_PATTERN"
OUTCOME_NO_DATA = "NO_DATA"
OUTCOME_SKIPPED = "SKIPPED"
OUTCOME_ERROR = "ERROR"


@dataclass(frozen=True)
class Instrument:
    """A validated NSE futures contract, or an explicit FYERS symbol.

    ``expiry`` is optional for explicit symbols that were not resolved through
    the FYERS instrument master; when present it enables the expiry guard.
    """

    symbol: str
    underlying: str
    expiry: date | None = None
    description: str = ""
    lot_size: float | None = None
    is_index: bool = False

    @property
    def label(self) -> str:
        if self.expiry is None:
            return self.symbol
        return f"{self.symbol}  ·  {self.expiry:%d %b %Y}"


@dataclass(frozen=True)
class PatternConfig:
    """Configuration for the contract-start AVWAP pattern detector.

    Percentage thresholds are expressed as decimals (0.005 == 0.5%).
    """

    max_close_above_pct: float = 0.005
    max_close_below_pct: float = 0.002
    max_low_below_pct: float = 0.003
    max_body_ratio: float = 0.35
    min_candles: int = 1
    max_candles: int = 5
    max_window_range_pct: float = 0.02
    max_candle_range_atr: float | None = 2.0
    touch_tolerance_pct: float = 0.001
    consolidation_min_candles: int = 3
    consolidation_range_pct: float = 0.01
    hugging_min_candles: int = 2
    allowed_patterns: tuple[str, ...] = PATTERN_TYPES
    require_close_above_avwap: bool = False
    require_close_above_vwap: bool = False
    below_reference: str = "off"
    below_candle: str = "previous"

    def __post_init__(self) -> None:
        if self.min_candles < 1:
            raise ValueError("min_candles must be >= 1")
        if self.max_candles < self.min_candles:
            raise ValueError("max_candles must be >= min_candles")
        for name in (
            "max_close_above_pct",
            "max_close_below_pct",
            "max_low_below_pct",
            "max_body_ratio",
            "max_window_range_pct",
            "touch_tolerance_pct",
            "consolidation_range_pct",
        ):
            value = float(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_body_ratio > 1:
            raise ValueError("max_body_ratio must be <= 1")
        if self.max_candle_range_atr is not None and self.max_candle_range_atr <= 0:
            raise ValueError("max_candle_range_atr must be > 0 or None")
        unknown = set(self.allowed_patterns) - set(PATTERN_TYPES)
        if unknown:
            raise ValueError(f"Unknown pattern types: {sorted(unknown)}")
        if self.below_reference not in BELOW_REFERENCES:
            raise ValueError(f"Unknown below reference: {self.below_reference!r}")
        if self.below_candle not in BELOW_CANDLES:
            raise ValueError(f"Unknown below candle: {self.below_candle!r}")

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation persisted with every scan run."""
        return {
            "max_close_above_pct": self.max_close_above_pct,
            "max_close_below_pct": self.max_close_below_pct,
            "max_low_below_pct": self.max_low_below_pct,
            "max_body_ratio": self.max_body_ratio,
            "min_candles": self.min_candles,
            "max_candles": self.max_candles,
            "max_window_range_pct": self.max_window_range_pct,
            "max_candle_range_atr": self.max_candle_range_atr,
            "touch_tolerance_pct": self.touch_tolerance_pct,
            "consolidation_min_candles": self.consolidation_min_candles,
            "consolidation_range_pct": self.consolidation_range_pct,
            "hugging_min_candles": self.hugging_min_candles,
            "allowed_patterns": list(self.allowed_patterns),
            "require_close_above_avwap": self.require_close_above_avwap,
            "require_close_above_vwap": self.require_close_above_vwap,
            "below_reference": self.below_reference,
            "below_candle": self.below_candle,
        }


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class DetectedPattern:
    """A pattern found at the right edge of a completed-candle series."""

    pattern_type: str
    candle_count: int
    start_idx: int
    end_idx: int
    pattern_start: pd.Timestamp | None
    pattern_end: pd.Timestamp | None
    last_price: float
    avwap: float
    distance_pct: float
    avg_body_ratio: float
    max_body_ratio: float
    window_range_pct: float
    touched: bool
    anchor_timestamp: pd.Timestamp | None = None
    latest_atr: float | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Every field needed to explain the detection, JSON-safe.

        The original detector has no confidence score; none is added here.
        """
        return {
            "pattern_type": self.pattern_type,
            "candle_count": self.candle_count,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "pattern_start": _isoformat(self.pattern_start),
            "pattern_end": _isoformat(self.pattern_end),
            "last_price": float(self.last_price),
            "avwap": float(self.avwap),
            "distance_pct": float(self.distance_pct),
            "avg_body_ratio": float(self.avg_body_ratio),
            "max_body_ratio": float(self.max_body_ratio),
            "window_range_pct": float(self.window_range_pct),
            "touched": bool(self.touched),
            "anchor_timestamp": _isoformat(self.anchor_timestamp),
            "latest_atr": (float(self.latest_atr) if self.latest_atr is not None else None),
        }


@dataclass(frozen=True)
class ScanMatch:
    """A detected pattern linked to its futures contract."""

    instrument: Instrument
    pattern: DetectedPattern
    resolution: str = "60"

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def expiry(self) -> date | None:
        return self.instrument.expiry

    @property
    def pattern_type(self) -> str:
        return self.pattern.pattern_type

    def to_row(self) -> dict[str, Any]:
        pattern = self.pattern
        return {
            "Symbol": self.instrument.symbol,
            "Underlying": self.instrument.underlying,
            "Expiry": self.instrument.expiry,
            "Last Price": pattern.last_price,
            "Contract AVWAP": pattern.avwap,
            "Distance (%)": pattern.distance_pct,
            "Candles": pattern.candle_count,
            "Body Ratio": pattern.avg_body_ratio,
            "Max Body Ratio": pattern.max_body_ratio,
            "Pattern Range (%)": pattern.window_range_pct * 100.0,
            "Classification": pattern.pattern_type,
            "Pattern Timestamp": pattern.pattern_end,
            "ATR": pattern.latest_atr,
        }


@dataclass(frozen=True)
class ScanError:
    symbol: str
    message: str


@dataclass(frozen=True)
class InstrumentOutcome:
    """Result of scanning one instrument, for live progress display.

    This is reporting metadata only: it never changes detection or scoring.
    """

    symbol: str
    status: str
    underlying: str | None = None
    expiry: date | None = None
    pattern_type: str | None = None
    message: str | None = None
    candles: int = 0
    last_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "status": self.status,
            "pattern_type": self.pattern_type,
            "message": self.message,
            "candles": self.candles,
            "last_price": self.last_price,
        }


@dataclass
class ScanReport:
    """Result of one scanner run."""

    matches: list[ScanMatch] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    histories: dict[str, pd.DataFrame] = field(default_factory=dict)
    outcomes: list[InstrumentOutcome] = field(default_factory=list)
    scanned_count: int = 0
    generated_at: datetime | None = None
    resolution: str = "60"
    pattern_config: PatternConfig = field(default_factory=PatternConfig)

    def sorted_matches(self) -> list[ScanMatch]:
        return sorted(self.matches, key=lambda match: abs(match.pattern.distance_pct))

    def classification_counts(self) -> dict[str, int]:
        counts = {pattern_type: 0 for pattern_type in PATTERN_TYPES}
        for match in self.matches:
            counts[match.pattern_type] = counts.get(match.pattern_type, 0) + 1
        return counts

    def summary(self) -> dict[str, int]:
        counts = self.classification_counts()
        return {
            "scanned": self.scanned_count,
            "matches": len(self.matches),
            "touches": counts.get(PATTERN_TOUCH, 0),
            "hugging": counts.get(PATTERN_HUGGING, 0),
            "consolidations": counts.get(PATTERN_CONSOLIDATION, 0),
            "reclaims": counts.get(PATTERN_RECLAIM, 0),
            "errors": len(self.errors),
        }
