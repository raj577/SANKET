"""Pattern scan persistence: scan runs, candidates and execution metadata."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select

from app.market_data.fyers_client import FyersError
from app.models.enums import CandidateStatus, ScanStatus, ScanType
from app.models.scan import PatternCandidate, ScanRun
from app.services import pattern_scan_service

from .pattern_fixtures import (
    FakeHistoryService,
    add_indicators,
    ist,
    make_frame,
    make_instrument,
)

NOW = ist(2026, 11, 4, 16, 0)


def _scan(db, instruments, timeframe="60") -> uuid.UUID:
    scan = pattern_scan_service.create_scan(
        db, total_symbols=len(instruments), timeframe=timeframe
    )
    return scan.id


def _run(db, scan_id, *, frame=None, instruments=(), timeframe="60", **kwargs):
    pattern_scan_service.run_scan_job(
        scan_id,
        kwargs.pop("symbols", None),
        timeframe,
        True,
        True,
        history_service=FakeHistoryService(frame, **kwargs),
        instruments=list(instruments),
        now=NOW,
    )
    db.expire_all()
    scan = db.get(ScanRun, scan_id)
    assert scan is not None
    return scan


def _candidates(db, scan_id) -> list[PatternCandidate]:
    return list(
        db.scalars(
            select(PatternCandidate)
            .where(PatternCandidate.scan_id == scan_id)
            .order_by(PatternCandidate.symbol)
        ).all()
    )


# ---------------------------------------------------------------- scan runs


def test_create_scan_records_type_and_timeframe(db_session):
    scan = pattern_scan_service.create_scan(
        db_session, total_symbols=3, timeframe="15"
    )
    assert scan.scan_type == ScanType.AVWAP_PATTERN.value
    assert scan.timeframe == "15"
    assert scan.status == ScanStatus.PENDING.value
    assert scan.total_symbols == 3
    assert scan.trigger == "pattern"


def test_successful_run_persists_candidates_and_metadata(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session,
        scan_id,
        frame=make_frame(pattern_count=3),
        instruments=[instrument],
    )

    assert scan.status == ScanStatus.COMPLETED.value
    assert scan.completed_at is not None
    assert scan.candidates_processed is True
    assert scan.successful_symbols == 1
    assert scan.failed_symbols == 0
    assert scan.error_message is None
    assert scan.long_candidates_count == 0
    assert scan.short_candidates_count == 0
    assert scan.scanner_version == "avwap-pattern-1.0.0"
    assert scan.scan_type == ScanType.AVWAP_PATTERN.value
    assert scan.timeframe == "60"

    candidates = _candidates(db_session, scan_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.symbol == "NSE:NIFTY26NOVFUT"
    assert candidate.underlying == "NIFTY"
    assert candidate.timeframe == "60"
    assert candidate.pattern_type == "AVWAP CONSOLIDATION"
    assert candidate.candle_count == 3
    assert candidate.status == CandidateStatus.PENDING.value
    assert candidate.touched is True
    assert isinstance(candidate.last_price, Decimal)
    assert candidate.avwap > 0
    assert candidate.anchor_at is not None
    assert candidate.pattern_end is not None
    assert "AVWAP CONSOLIDATION" in candidate.reason
    assert "candle(s)" in candidate.reason

    metadata = candidate.detector_metadata
    assert metadata is not None
    assert metadata["pattern_type"] == "AVWAP CONSOLIDATION"
    assert metadata["candle_count"] == 3
    assert "confidence" not in metadata
    assert "score" not in metadata
    assert metadata["end_idx"] == metadata["start_idx"] + 2

    config = scan.scanner_config
    assert config["scan_type"] == ScanType.AVWAP_PATTERN.value
    assert config["timeframe"] == "60"
    assert config["provider"] == "fyers"
    assert config["instrument_source"] == "futures_universe"
    assert config["detector"]["max_close_above_pct"] == 0.005
    execution = config["execution"]
    assert execution["instruments_resolved"] == 1
    assert execution["matches"] == 1
    assert execution["duration_ms"] >= 0
    assert execution["classification_counts"]["AVWAP CONSOLIDATION"] == 1
    assert execution["classification_counts"]["AVWAP TOUCH"] == 0
    assert execution["histories"]["NSE:NIFTY26NOVFUT"]["candles"] > 0


def test_run_without_matches_completes_and_writes_no_candidates(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    # A far-above-AVWAP close is not a pattern.
    no_pattern = make_frame(
        pattern_candles=[
            {
                "open": 100.90,
                "high": 101.20,
                "low": 100.70,
                "close": 101.00,
                "volume": 1000.0,
            }
        ]
    )
    scan_id = _scan(db_session, [instrument])
    scan = _run(db_session, scan_id, frame=no_pattern, instruments=[instrument])

    assert scan.status == ScanStatus.COMPLETED.value
    assert _candidates(db_session, scan_id) == []
    assert scan.scanner_config["execution"]["matches"] == 0


def test_partial_run_marks_scan_partial_and_records_errors(db_session):
    good = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    bad = make_instrument("NSE:SBIN26NOVFUT", "SBIN")
    scan_id = _scan(db_session, [good, bad])
    scan = _run(
        db_session,
        scan_id,
        frame=make_frame(pattern_count=1),
        instruments=[good, bad],
        failures={"NSE:SBIN26NOVFUT": "No completed historical candles available"},
    )

    assert scan.status == ScanStatus.PARTIAL.value
    assert scan.successful_symbols == 1
    assert scan.failed_symbols == 1
    assert "NSE:SBIN26NOVFUT" in (scan.error_message or "")
    assert len(_candidates(db_session, scan_id)) == 1
    execution = scan.scanner_config["execution"]
    assert execution["errors"][0]["symbol"] == "NSE:SBIN26NOVFUT"
    assert execution["instruments_requested"] == 2
    assert execution["instruments_resolved"] == 2


def test_all_symbols_failing_marks_scan_failed(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session,
        scan_id,
        frame=make_frame(pattern_count=1),
        instruments=[instrument],
        failures={"NSE:NIFTY26NOVFUT": "FYERS request failed"},
    )

    assert scan.status == ScanStatus.FAILED.value
    assert scan.successful_symbols == 0
    assert scan.failed_symbols == 1


def test_expired_contract_is_reported_and_not_detected(db_session):
    expired = make_instrument("NSE:OLD26JANFUT", "OLD", expiry=pd.Timestamp("2020-01-30").date())
    scan_id = _scan(db_session, [expired])
    scan = _run(
        db_session,
        scan_id,
        frame=make_frame(pattern_count=1),
        instruments=[expired],
    )

    assert scan.status == ScanStatus.FAILED.value
    assert "expired" in (scan.error_message or "").lower()
    assert _candidates(db_session, scan_id) == []


def test_fatal_error_persists_failure_reason(db_session):
    scan_id = _scan(db_session, [])
    scan = _run(db_session, scan_id, instruments=[])

    assert scan.status == ScanStatus.FAILED.value
    assert scan.completed_at is not None
    assert "No instruments resolved" in (scan.error_message or "")
    execution = scan.scanner_config["execution"]
    assert execution["matches"] == 0
    assert "No instruments resolved" in execution["fatal_error"]


def test_auth_failure_aborts_the_whole_run(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")

    class AuthFailingHistory(FakeHistoryService):
        def fetch(self, instrument, resolution=None, end_date=None):
            raise FyersError("FYERS access token expired or was rejected")

    scan_id = _scan(db_session, [instrument])
    pattern_scan_service.run_scan_job(
        scan_id,
        None,
        "60",
        True,
        True,
        history_service=AuthFailingHistory(),
        instruments=[instrument],
        now=NOW,
    )
    db_session.expire_all()
    scan = db_session.get(ScanRun, scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.FAILED.value
    assert "token" in (scan.error_message or "").lower()


def test_missing_scan_id_is_tolerated(db_session):
    """A deleted scan must not crash the background job."""
    pattern_scan_service.run_scan_job(
        uuid.uuid4(),
        None,
        "60",
        True,
        True,
        history_service=FakeHistoryService(make_frame(pattern_count=1)),
        instruments=[make_instrument()],
        now=NOW,
    )


def test_duplicate_matches_are_persisted_once(db_session):
    """Two different symbols may match, but a repeated symbol/timeframe pair not."""
    first = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    second = make_instrument("NSE:BANKNIFTY26NOVFUT", "BANKNIFTY")
    frame = make_frame(pattern_count=2)
    scan_id = _scan(db_session, [first, second])
    scan = _run(db_session, scan_id, frame=frame, instruments=[first, second])

    assert scan.scanner_config["execution"]["matches"] == 2
    candidates = _candidates(db_session, scan_id)
    assert {candidate.symbol for candidate in candidates} == {
        "NSE:NIFTY26NOVFUT",
        "NSE:BANKNIFTY26NOVFUT",
    }


def test_each_classification_is_persisted(db_session):
    """TOUCH, HUGGING, CONSOLIDATION and RECLAIM all round-trip to the table."""
    reclaim = [
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
    cases = {
        "AVWAP TOUCH": make_frame(pattern_count=1),
        "AVWAP HUGGING": make_frame(pattern_count=2),
        "AVWAP CONSOLIDATION": make_frame(pattern_count=4),
        "AVWAP RECLAIM": make_frame(pattern_candles=reclaim),
    }

    for expected, frame in cases.items():
        symbol = f"NSE:{expected.replace(' ', '').replace('AVWAP', 'X')}26NOVFUT"
        instrument = make_instrument(symbol, "X")
        scan_id = _scan(db_session, [instrument])
        scan = _run(db_session, scan_id, frame=frame, instruments=[instrument])
        candidates = _candidates(db_session, scan_id)
        assert len(candidates) == 1, (expected, scan.error_message)
        assert candidates[0].pattern_type == expected
        assert scan.scanner_config["execution"]["classification_counts"][expected] == 1


def test_pattern_summary_counts_detections(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session, scan_id, frame=make_frame(pattern_count=2), instruments=[instrument]
    )
    candidates = _candidates(db_session, scan_id)
    summary = pattern_scan_service.pattern_summary(scan, candidates)
    assert summary["timeframe"] == "60"
    assert summary["matches"] == 1
    assert summary["instruments_resolved"] == 1
    assert summary["errors"] == 0
    assert summary["classification_counts"]["AVWAP HUGGING"] == 1
    assert set(summary["classification_counts"]) == {
        "AVWAP TOUCH",
        "AVWAP HUGGING",
        "AVWAP CONSOLIDATION",
        "AVWAP RECLAIM",
    }


def test_get_scan_only_returns_pattern_scans(db_session):
    from datetime import datetime, timezone

    from app.core.exceptions import NotFoundError

    oi_scan = ScanRun(
        started_at=datetime.now(timezone.utc),
        status=ScanStatus.COMPLETED.value,
        scan_type=ScanType.OI.value,
    )
    db_session.add(oi_scan)
    db_session.commit()

    with pytest.raises(NotFoundError):
        pattern_scan_service.get_scan(db_session, oi_scan.id)

    pattern_scan = pattern_scan_service.create_scan(
        db_session, total_symbols=1, timeframe="60"
    )
    assert pattern_scan_service.get_scan(db_session, pattern_scan.id).id == pattern_scan.id


def test_engine_enrichment_adds_indicator_columns():
    from app.scanner.patterns.engine import enrich_frame

    frame = add_indicators(make_frame(pattern_count=1)).drop(
        columns=["avwap", "session_vwap", "atr"]
    )
    enriched = enrich_frame(frame)
    assert {"avwap", "session_vwap", "atr"} <= set(enriched.columns)
    assert pd.notna(enriched["avwap"].iloc[-1])
    assert pd.notna(enriched["session_vwap"].iloc[-1])


# ------------------------------------------------------- per-symbol progress


def test_successful_run_records_progress_and_symbol_list(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session, scan_id, frame=make_frame(pattern_count=3), instruments=[instrument]
    )

    progress = pattern_scan_service.pattern_progress(scan, matched=1)
    assert progress["state"] == "finished"
    assert progress["processed"] == 1
    assert progress["total"] == 1
    assert progress["percent"] == 100
    assert progress["matched"] == 1
    assert progress["failed"] == 0
    assert progress["pending"] == 0

    symbols = pattern_scan_service.pattern_symbols(scan)
    assert len(symbols) == 1
    entry = symbols[0]
    assert entry["symbol"] == "NSE:NIFTY26NOVFUT"
    assert entry["underlying"] == "NIFTY"
    assert entry["status"] == "MATCHED"
    assert entry["pattern_type"] == "AVWAP CONSOLIDATION"
    assert entry["candles"] == 43
    assert entry["last_price"] > 0
    assert entry["message"] is None


def test_no_pattern_run_marks_the_symbol_as_scanned(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session, scan_id, frame=make_frame(pattern_count=0), instruments=[instrument]
    )

    assert scan.status == ScanStatus.COMPLETED.value
    progress = pattern_scan_service.pattern_progress(scan)
    assert progress["processed"] == 1
    assert progress["matched"] == 0
    assert progress["failed"] == 0

    entry = pattern_scan_service.pattern_symbols(scan)[0]
    assert entry["status"] == "NO_PATTERN"
    assert entry["pattern_type"] is None
    assert entry["candles"] == 40


def test_symbol_errors_are_listed_with_their_message(db_session):
    good = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    bad = make_instrument("NSE:BANKNIFTY26NOVFUT", "BANKNIFTY")
    scan_id = _scan(db_session, [good, bad])
    scan = _run(
        db_session,
        scan_id,
        frame=make_frame(pattern_count=2),
        instruments=[good, bad],
        failures={bad.symbol: "history request failed"},
    )

    assert scan.status == ScanStatus.PARTIAL.value
    progress = pattern_scan_service.pattern_progress(scan, matched=1)
    assert progress["processed"] == 2
    assert progress["matched"] == 1
    assert progress["failed"] == 1
    assert progress["percent"] == 100

    by_symbol = {
        entry["symbol"]: entry for entry in pattern_scan_service.pattern_symbols(scan)
    }
    assert by_symbol[good.symbol]["status"] == "MATCHED"
    assert by_symbol[bad.symbol]["status"] == "ERROR"
    assert by_symbol[bad.symbol]["message"] == "history request failed"


def test_insufficient_candles_are_listed_as_no_data(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan_id = _scan(db_session, [instrument])
    scan = _run(
        db_session, scan_id, frame=pd.DataFrame(), instruments=[instrument]
    )

    entry = pattern_scan_service.pattern_symbols(scan)[0]
    assert entry["status"] == "NO_DATA"
    assert "No completed candles" in entry["message"]


def test_expired_contract_is_listed_as_skipped(db_session):
    from datetime import date, timedelta

    expired = make_instrument(
        "NSE:NIFTY25OCTFUT", "NIFTY", expiry=date(2026, 10, 30)
    )
    scan_id = _scan(db_session, [expired])
    scan = _run(
        db_session, scan_id, frame=make_frame(pattern_count=2), instruments=[expired]
    )

    entry = pattern_scan_service.pattern_symbols(scan)[0]
    assert entry["status"] == "SKIPPED"
    assert "expired" in (entry["message"] or "").lower()


def test_resolution_errors_seed_the_symbol_list_as_errors():
    from app.scanner.patterns.models import InstrumentOutcome

    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    entries = pattern_scan_service._initial_symbol_entries(
        [instrument], [("BADSYM", "Unknown symbol")]
    )
    assert [entry["symbol"] for entry in entries] == ["BADSYM", instrument.symbol]
    assert entries[0]["status"] == "ERROR"
    assert entries[0]["message"] == "Unknown symbol"
    assert entries[1]["status"] == "PENDING"
    # Outcome rows update the entry in place without losing its identity.
    entries[1].update(
        InstrumentOutcome(
            symbol=instrument.symbol,
            status="NO_PATTERN",
            underlying=instrument.underlying,
            expiry=instrument.expiry,
            candles=40,
            last_price=100.5,
        ).to_dict()
    )
    assert entries[1]["status"] == "NO_PATTERN"
    assert entries[1]["candles"] == 40


def test_fatal_auth_failure_marks_remaining_symbols_as_stopped(db_session):
    first = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    second = make_instrument("NSE:BANKNIFTY26NOVFUT", "BANKNIFTY")

    class AuthFailingHistory(FakeHistoryService):
        def fetch(self, instrument, resolution=None, end_date=None):
            raise FyersError("FYERS access token expired or was rejected")

    scan_id = _scan(db_session, [first, second])
    pattern_scan_service.run_scan_job(
        scan_id,
        None,
        "60",
        True,
        True,
        history_service=AuthFailingHistory(),
        instruments=[first, second],
        now=NOW,
    )
    db_session.expire_all()
    scan = db_session.get(ScanRun, scan_id)

    assert scan.status == ScanStatus.FAILED.value
    progress = pattern_scan_service.pattern_progress(scan)
    assert progress["state"] == "finished"
    assert progress["processed"] == 1
    assert progress["percent"] == 50
    entries = pattern_scan_service.pattern_symbols(scan)
    assert [entry["status"] for entry in entries] == ["ERROR", "ERROR"]
    assert "token" in (entries[0]["message"] or "").lower()
    assert "Scan stopped" in (entries[1]["message"] or "")

