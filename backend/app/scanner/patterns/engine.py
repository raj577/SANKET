"""Scan orchestration: history -> indicators -> pattern detection.

Ported from the original AVWAP scanner (``scanner/scan_engine.py``). The
orchestration order is unchanged; the only differences are that an instrument
without a known expiry skips the expiry guard, and Project A's FYERS errors are
detected by message.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone as dt_timezone
from typing import Callable, Sequence

import pandas as pd

from .candles import drop_incomplete_candles
from .detector import PatternDetector
from .history import PatternHistoryService, _is_auth_error
from .indicators import compute_atr, compute_contract_avwap, compute_session_vwap
from .models import (
    OUTCOME_ERROR,
    OUTCOME_MATCHED,
    OUTCOME_NO_DATA,
    OUTCOME_NO_PATTERN,
    OUTCOME_SKIPPED,
    Instrument,
    InstrumentOutcome,
    PatternConfig,
    ScanError,
    ScanMatch,
    ScanReport,
)

logger = logging.getLogger("sensibull.patterns.engine")

ProgressCallback = Callable[[int, int, InstrumentOutcome], None]


def _failure_status(message: str) -> str:
    """Map an engine failure message to a progress-list state.

    Messages are produced in this module, so the mapping stays stable; the
    detector itself is untouched.
    """
    if message.startswith("Contract expired"):
        return OUTCOME_SKIPPED
    if message == "No completed candles available":
        return OUTCOME_NO_DATA
    return OUTCOME_ERROR


def enrich_frame(
    candles: pd.DataFrame,
    *,
    timezone: str = "Asia/Kolkata",
    atr_period: int = 14,
) -> pd.DataFrame:
    """Attach the detector's ``avwap``, ``session_vwap`` and ``atr`` columns."""

    frame = candles.copy()
    frame["avwap"] = compute_contract_avwap(frame, anchor_index=0)
    frame["session_vwap"] = compute_session_vwap(frame, timezone=timezone)
    frame["atr"] = compute_atr(frame, period=atr_period)
    return frame


def scan_instruments(
    history_service: PatternHistoryService,
    instruments: Sequence[Instrument],
    *,
    resolution: str = "60",
    pattern_config: PatternConfig | None = None,
    now: pd.Timestamp | datetime | None = None,
    timezone: str = "Asia/Kolkata",
    progress_callback: ProgressCallback | None = None,
) -> ScanReport:
    """Scan a sequence of instruments and return matches plus per-symbol errors."""

    config = pattern_config or PatternConfig()
    detector = PatternDetector(config)
    today = (pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=timezone)).date()
    now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=timezone)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize(timezone)
    else:
        now_ts = now_ts.tz_convert(timezone)

    report = ScanReport(
        generated_at=datetime.now(dt_timezone.utc),
        resolution=str(resolution),
        pattern_config=config,
    )
    total = len(instruments)
    report.scanned_count = total

    def emit(position: int, outcome: InstrumentOutcome) -> None:
        report.outcomes.append(outcome)
        if progress_callback is None:
            return
        try:
            progress_callback(position, total, outcome)
        except Exception:
            logger.debug("Progress callback failed", exc_info=True)

    for position, instrument in enumerate(instruments, start=1):
        fatal: Exception | None = None
        try:
            if instrument.expiry is not None and instrument.expiry < today:
                raise ValueError(f"Contract expired on {instrument.expiry:%Y-%m-%d}")

            candles = history_service.fetch(
                instrument,
                resolution=resolution,
                end_date=today,
            )
            candles = drop_incomplete_candles(
                candles,
                resolution=resolution,
                now=now_ts,
                timezone=timezone,
            )
            if candles.empty:
                raise ValueError("No completed candles available")

            frame = enrich_frame(candles, timezone=timezone)
            detected = detector.detect(frame)
            last_price = float(frame["close"].iloc[-1])
            if detected is not None:
                match = ScanMatch(
                    instrument=instrument,
                    pattern=detected,
                    resolution=str(resolution),
                )
                report.matches.append(match)
                report.histories[instrument.symbol] = frame
                outcome = InstrumentOutcome(
                    symbol=instrument.symbol,
                    status=OUTCOME_MATCHED,
                    underlying=instrument.underlying,
                    expiry=instrument.expiry,
                    pattern_type=detected.pattern_type,
                    candles=int(len(candles)),
                    last_price=last_price,
                )
            else:
                outcome = InstrumentOutcome(
                    symbol=instrument.symbol,
                    status=OUTCOME_NO_PATTERN,
                    underlying=instrument.underlying,
                    expiry=instrument.expiry,
                    candles=int(len(candles)),
                    last_price=last_price,
                )
        except Exception as exc:  # noqa: BLE001 - one symbol must not stop the scan
            message = str(exc) or type(exc).__name__
            outcome = InstrumentOutcome(
                symbol=instrument.symbol,
                status=_failure_status(message),
                underlying=instrument.underlying,
                expiry=instrument.expiry,
                message=message,
            )
            if _is_auth_error(exc):
                # A dead token invalidates the whole run.
                fatal = exc
            else:
                logger.warning("Pattern scan skipped %s: %s", instrument.symbol, message)
                report.errors.append(ScanError(instrument.symbol, message))
        finally:
            emit(position, outcome)
        if fatal is not None:
            raise fatal

    logger.info(
        "Pattern scan complete: %s instruments, %s matches, %s errors",
        report.scanned_count,
        len(report.matches),
        len(report.errors),
    )
    return report
