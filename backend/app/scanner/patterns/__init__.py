"""Isolated AVWAP/VWAP option-pattern scanner.

This package is independent of the OI scanner: it shares no scoring, schema or
orchestration code. Public entry points are re-exported here for convenience.
"""

from .candles import (
    NoMarketDataError,
    drop_incomplete_candles,
    normalize_candles,
    resolution_minutes,
)
from .detector import PatternDetector, compute_candle_metrics, small_candle_mask
from .engine import enrich_frame, scan_instruments
from .history import (
    DEFAULT_INDEX_UNDERLYINGS,
    DEFAULT_INSTRUMENT_MASTER_URL,
    InstrumentMasterError,
    InstrumentMasterProvider,
    PatternHistoryService,
    parse_instrument_master,
    resolve_instrument,
    select_active_futures,
    to_instruments,
)
from .models import (
    BELOW_CANDLES,
    BELOW_REFERENCES,
    PATTERN_CONSOLIDATION,
    PATTERN_HUGGING,
    PATTERN_RECLAIM,
    PATTERN_SCANNER_VERSION,
    PATTERN_TOUCH,
    PATTERN_TYPES,
    DetectedPattern,
    Instrument,
    InstrumentOutcome,
    PatternConfig,
    ScanError,
    ScanMatch,
    ScanReport,
)

__all__ = [
    "BELOW_CANDLES",
    "BELOW_REFERENCES",
    "DEFAULT_INDEX_UNDERLYINGS",
    "DEFAULT_INSTRUMENT_MASTER_URL",
    "DetectedPattern",
    "Instrument",
    "InstrumentMasterError",
    "InstrumentMasterProvider",
    "InstrumentOutcome",
    "NoMarketDataError",
    "PATTERN_CONSOLIDATION",
    "PATTERN_HUGGING",
    "PATTERN_RECLAIM",
    "PATTERN_SCANNER_VERSION",
    "PATTERN_TOUCH",
    "PATTERN_TYPES",
    "PatternConfig",
    "PatternDetector",
    "PatternHistoryService",
    "ScanError",
    "ScanMatch",
    "ScanReport",
    "compute_candle_metrics",
    "drop_incomplete_candles",
    "enrich_frame",
    "normalize_candles",
    "parse_instrument_master",
    "resolution_minutes",
    "resolve_instrument",
    "scan_instruments",
    "select_active_futures",
    "small_candle_mask",
    "to_instruments",
]
