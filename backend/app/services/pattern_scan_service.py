"""AVWAP/VWAP pattern scan lifecycle.

Kept separate from :mod:`app.services.scan_service` (OI) on purpose. This
module creates ``ScanRun`` rows with ``scan_type = AVWAP_PATTERN``, persists
``PatternCandidate`` rows and records execution metadata. It never touches OI
candidate rows or scoring.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.market_data.fyers_client import FyersClient
from app.models.enums import AuditAction, CandidateStatus, ScanStatus, ScanType
from app.models.scan import PatternCandidate, ScanRun
from app.models.user import User
from app.scanner.patterns import (
    PATTERN_SCANNER_VERSION,
    PATTERN_TYPES,
    Instrument,
    InstrumentMasterProvider,
    InstrumentOutcome,
    PatternConfig,
    PatternHistoryService,
    ScanReport,
    resolve_instrument,
    scan_instruments,
)
from app.scanner.patterns.candles import resolution_minutes
from app.scanner.patterns.models import (
    OUTCOME_ERROR,
    OUTCOME_MATCHED,
    OUTCOME_NO_DATA,
    OUTCOME_PENDING,
    OUTCOME_SCANNING,
    OUTCOME_SKIPPED,
)
from app.services import audit_service, scan_service

logger = logging.getLogger("sensibull.patterns.service")

#: States that count as "not scanned successfully" in the run counters.
FAILED_STATES = frozenset({OUTCOME_ERROR, OUTCOME_NO_DATA, OUTCOME_SKIPPED})

PROVIDER_NOT_READY = (
    "FYERS is not configured; connect FYERS in admin settings or set "
    "FYERS_ACCESS_TOKEN before running the pattern scanner"
)


def provider_ready() -> tuple[bool, str]:
    """Return whether FYERS can serve historical candles right now."""
    try:
        client = FyersClient()
    except Exception as exc:  # noqa: BLE001 - token store problems must not 500
        return False, str(exc) or PROVIDER_NOT_READY
    if client.configured:
        return True, ""
    return False, PROVIDER_NOT_READY


def validate_timeframe(value: str | None) -> str:
    settings = get_settings()
    allowed = settings.pattern_timeframes_list
    timeframe = (value or settings.pattern_default_timeframe).strip().upper()
    if timeframe not in allowed:
        raise ValidationError(
            f"Unsupported timeframe {timeframe!r}; allowed: {', '.join(allowed)}"
        )
    resolution_minutes(timeframe)
    return timeframe


def normalize_symbols(symbols: Sequence[str] | None) -> list[str]:
    settings = get_settings()
    if not symbols:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        text = str(raw or "").strip().upper()
        if not text:
            continue
        if len(text) > 64:
            raise ValidationError(f"Symbol is too long: {text[:64]!r}")
        if not all(character.isalnum() or character in ":_.-" for character in text):
            raise ValidationError(f"Invalid symbol: {text!r}")
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    if len(cleaned) > settings.pattern_max_symbols:
        raise ValidationError(
            f"At most {settings.pattern_max_symbols} symbols can be scanned per run"
        )
    return cleaned


def create_scan(
    db: Session,
    *,
    total_symbols: int,
    timeframe: str,
    trigger: str = "pattern",
) -> ScanRun:
    return scan_service.create_scan(
        db,
        total_symbols=total_symbols,
        trigger=trigger,
        scan_type=ScanType.AVWAP_PATTERN.value,
        timeframe=timeframe,
    )


def get_scan(db: Session, scan_id: uuid.UUID) -> ScanRun:
    scan = db.get(ScanRun, scan_id)
    if scan is None or scan.scan_type != ScanType.AVWAP_PATTERN.value:
        raise NotFoundError("Pattern scan not found")
    return scan


def resolve_instruments(
    symbols: Sequence[str] | None,
    *,
    include_index: bool = True,
    current_expiry_only: bool = True,
) -> tuple[list[Instrument], list[tuple[str, str]]]:
    """Resolve explicit symbols or the current futures universe.

    Returns ``(instruments, resolution_errors)`` where each error is a
    ``(symbol, message)`` pair, so the admin symbol list can show the request
    that could not be resolved.
    """

    settings = get_settings()
    requested = list(symbols or [])
    needs_master = not requested or any(":" not in item for item in requested)
    master = None
    provider: InstrumentMasterProvider | None = None
    if needs_master:
        provider = InstrumentMasterProvider(
            settings.pattern_instrument_master_url,
            ttl_seconds=settings.pattern_instrument_cache_ttl_seconds,
            timezone=settings.timezone,
        )
        master = provider.load()

    if not requested:
        assert provider is not None
        instruments = provider.instruments(
            current_expiry_only=current_expiry_only,
            include_index=include_index,
        )
        if not instruments:
            raise ValidationError("No active NSE futures contracts were found")
        return instruments, []

    instruments: list[Instrument] = []
    errors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for symbol in requested:
        try:
            instrument = resolve_instrument(symbol, master)
        except ValueError as exc:
            errors.append((str(symbol or "").strip().upper()[:64], str(exc)))
            continue
        if instrument.symbol in seen:
            continue
        seen.add(instrument.symbol)
        instruments.append(instrument)
    return instruments, errors


def _decimal(value: Any, places: int) -> Decimal:
    return Decimal(str(round(float(value), places)))


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.to_pydatetime()


def _pattern_reason(match) -> str:
    pattern = match.pattern
    return (
        f"{pattern.pattern_type} · {pattern.candle_count} candle(s) · "
        f"close {pattern.distance_pct:+.2f}% vs AVWAP"
    )


def _persist_matches(db: Session, scan: ScanRun, report: ScanReport) -> int:
    persisted = 0
    seen: set[tuple[str, str]] = set()
    for match in report.matches:
        pattern = match.pattern
        key = (match.instrument.symbol, report.resolution)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            PatternCandidate(
                scan_id=scan.id,
                symbol=match.instrument.symbol[:64],
                underlying=match.instrument.underlying[:32],
                expiry=match.instrument.expiry,
                timeframe=report.resolution[:8],
                pattern_type=pattern.pattern_type,
                candle_count=int(pattern.candle_count),
                last_price=_decimal(pattern.last_price, 4),
                avwap=_decimal(pattern.avwap, 4),
                distance_pct=_decimal(pattern.distance_pct, 6),
                avg_body_ratio=_decimal(pattern.avg_body_ratio, 6),
                max_body_ratio=_decimal(pattern.max_body_ratio, 6),
                window_range_pct=_decimal(pattern.window_range_pct, 6),
                touched=bool(pattern.touched),
                atr=(
                    _decimal(pattern.latest_atr, 6)
                    if pattern.latest_atr is not None
                    else None
                ),
                anchor_at=_as_datetime(pattern.anchor_timestamp),
                pattern_start=_as_datetime(pattern.pattern_start),
                pattern_end=_as_datetime(pattern.pattern_end),
                status=CandidateStatus.PENDING.value,
                reason=_pattern_reason(match),
                detector_metadata=pattern.to_metadata(),
            )
        )
        persisted += 1
    return persisted


def _history_metadata(report: ScanReport) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for symbol, frame in report.histories.items():
        if frame.empty:
            continue
        metadata[symbol] = {
            "candles": int(len(frame)),
            "first": _as_datetime(frame["timestamp"].iloc[0]).isoformat()
            if _as_datetime(frame["timestamp"].iloc[0])
            else None,
            "last": _as_datetime(frame["timestamp"].iloc[-1]).isoformat()
            if _as_datetime(frame["timestamp"].iloc[-1])
            else None,
        }
    return metadata


def _symbol_entry(
    symbol: str,
    *,
    underlying: str | None = None,
    expiry=None,
    status: str = OUTCOME_PENDING,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "underlying": underlying,
        "expiry": expiry.isoformat() if expiry else None,
        "status": status,
        "pattern_type": None,
        "message": None,
        "candles": 0,
        "last_price": None,
    }


def _initial_symbol_entries(
    instruments: Sequence[Instrument],
    resolution_errors: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for symbol, message in resolution_errors:
        entry = _symbol_entry(symbol, status=OUTCOME_ERROR)
        entry["message"] = message
        entries.append(entry)
    for instrument in instruments:
        entries.append(
            _symbol_entry(
                instrument.symbol,
                underlying=instrument.underlying,
                expiry=instrument.expiry,
            )
        )
    return entries


def _progress_counts(entries: Sequence[dict[str, Any]], *, total: int, processed: int) -> dict[str, Any]:
    matched = sum(1 for entry in entries if entry["status"] == OUTCOME_MATCHED)
    failed = sum(1 for entry in entries if entry["status"] in FAILED_STATES)
    return {
        "state": "finished" if processed >= total else "running",
        "processed": processed,
        "total": total,
        "percent": 100 if total and processed >= total else int(processed / total * 100) if total else 0,
        "matched": matched,
        "failed": failed,
        "pending": max(total - processed, 0),
    }


def _save_symbol_state(
    session: Session,
    scan: ScanRun,
    entries: Sequence[dict[str, Any]],
    progress: dict[str, Any],
) -> None:
    payload = dict(scan.scanner_config or {})
    payload["symbols"] = [dict(entry) for entry in entries]
    payload["progress"] = progress
    scan.scanner_config = payload
    session.commit()


def run_scan_job(
    scan_id: uuid.UUID,
    symbols: Sequence[str] | None,
    timeframe: str,
    include_index: bool,
    current_expiry_only: bool,
    *,
    history_service: PatternHistoryService | None = None,
    instruments: Sequence[Instrument] | None = None,
    pattern_config: PatternConfig | None = None,
    now: pd.Timestamp | datetime | None = None,
) -> None:
    """Background job: resolve instruments -> candles -> indicators -> detect."""

    from app.db.session import get_sessionmaker

    settings = get_settings()
    config = pattern_config or PatternConfig()
    session = get_sessionmaker()()
    started = utcnow()
    scan: ScanRun | None = None
    entries: list[dict[str, Any]] = []
    total = 0
    processed = 0
    try:
        scan = session.get(ScanRun, scan_id)
        if scan is None:
            logger.warning("pattern_scan_missing", extra={"scan_id": str(scan_id)})
            return
        scan.status = ScanStatus.RUNNING.value
        session.commit()

        resolution_errors: list[tuple[str, str]] = []
        if instruments is None:
            instruments, resolution_errors = resolve_instruments(
                symbols,
                include_index=include_index,
                current_expiry_only=current_expiry_only,
            )
        instrument_list = list(instruments)

        scan.total_symbols = len(instrument_list)
        session.commit()

        total = len(instrument_list)
        entries = _initial_symbol_entries(instrument_list, resolution_errors)
        by_symbol = {entry["symbol"]: entry for entry in entries}
        resolved_offset = len(resolution_errors)
        if resolved_offset < len(entries):
            entries[resolved_offset]["status"] = OUTCOME_SCANNING
        # Publish the resolved symbols immediately so the admin progress list
        # has content even while the first candle request is in flight.
        _save_symbol_state(
            session,
            scan,
            entries,
            _progress_counts(entries, total=total, processed=0),
        )

        if not instrument_list:
            raise ValidationError(
                "; ".join(message for _, message in resolution_errors)
                or "No instruments resolved"
            )

        if history_service is None:
            history_service = PatternHistoryService(
                FyersClient(),
                default_resolution=timeframe,
                lookback_days=settings.pattern_lookback_days,
                chunk_days=settings.pattern_history_chunk_days,
                timezone=settings.timezone,
                request_pause_seconds=settings.pattern_history_pause_seconds,
            )

        def progress(position: int, total_count: int, outcome: InstrumentOutcome) -> None:
            nonlocal processed
            processed = max(processed, position)
            entry = by_symbol.get(outcome.symbol)
            if entry is not None:
                entry.update(outcome.to_dict())
            next_index = resolved_offset + position
            if next_index < len(entries) and entries[next_index]["status"] == OUTCOME_PENDING:
                entries[next_index]["status"] = OUTCOME_SCANNING

            instrument_failed = sum(
                1 for item in entries[resolved_offset:] if item["status"] in FAILED_STATES
            )
            scan.status = ScanStatus.RUNNING.value
            scan.last_progress_symbol = outcome.symbol[:64]
            scan.total_symbols = total_count
            scan.successful_symbols = max(position - instrument_failed, 0)
            scan.failed_symbols = len(resolution_errors) + instrument_failed
            _save_symbol_state(
                session,
                scan,
                entries,
                _progress_counts(entries, total=total_count, processed=position),
            )

        report = scan_instruments(
            history_service,
            instrument_list,
            resolution=timeframe,
            pattern_config=config,
            now=now,
            timezone=settings.timezone,
            progress_callback=progress,
        )

        persisted = _persist_matches(session, scan, report)
        failed = len(report.errors) + len(resolution_errors)
        scan.successful_symbols = max(len(instrument_list) - len(report.errors), 0)
        scan.failed_symbols = failed
        scan.long_candidates_count = 0
        scan.short_candidates_count = 0
        scan.candidates_processed = True
        scan.scanner_version = PATTERN_SCANNER_VERSION
        scan.completed_at = utcnow()

        if report.matches and failed:
            scan.status = ScanStatus.PARTIAL.value
        elif report.matches or not failed:
            scan.status = ScanStatus.COMPLETED.value
        else:
            scan.status = ScanStatus.FAILED.value

        error_messages = [
            f"{error.symbol}: {error.message}" for error in report.errors
        ] + [f"{symbol}: {message}" for symbol, message in resolution_errors]
        scan.error_message = "; ".join(error_messages[:20]) or None

        finished = utcnow()
        config_payload = dict(scan.scanner_config or {})
        config_payload.update(
            {
                "scan_type": ScanType.AVWAP_PATTERN.value,
                "scanner_version": PATTERN_SCANNER_VERSION,
                "timeframe": timeframe,
                "provider": "fyers",
                "instrument_source": "symbols" if symbols else "futures_universe",
                "detector": config.to_dict(),
                "execution": {
                    "started_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                    "duration_ms": int((finished - started).total_seconds() * 1000),
                    "instruments_requested": len(instrument_list)
                    + len(resolution_errors),
                    "instruments_resolved": len(instrument_list),
                    "matches": persisted,
                    "errors": [
                        {"symbol": error.symbol, "message": error.message}
                        for error in report.errors
                    ],
                    "resolution_errors": [
                        {"symbol": symbol, "message": message}
                        for symbol, message in resolution_errors
                    ],
                    "classification_counts": report.classification_counts(),
                    "histories": _history_metadata(report),
                },
            }
        )
        config_payload["symbols"] = [dict(entry) for entry in entries]
        config_payload["progress"] = _progress_counts(
            entries, total=total, processed=total
        )
        scan.scanner_config = config_payload
        session.commit()
        logger.info(
            "pattern_scan_complete",
            extra={
                "scan_id": str(scan_id),
                "matches": persisted,
                "errors": failed,
                "timeframe": timeframe,
            },
        )
    except Exception as exc:  # noqa: BLE001 - a background job must never stick
        logger.exception("pattern_scan_failed", extra={"scan_id": str(scan_id)})
        session.rollback()
        try:
            scan = session.get(ScanRun, scan_id)
            if scan is None:
                return
            finished = utcnow()
            scan.status = ScanStatus.FAILED.value
            scan.completed_at = finished
            stopped = str(exc) or type(exc).__name__
            scan.error_message = stopped[:4000]

            progress_payload: dict[str, Any] | None = None
            if entries:
                for entry in entries:
                    if entry["status"] in {OUTCOME_PENDING, OUTCOME_SCANNING}:
                        entry["status"] = OUTCOME_ERROR
                        entry["message"] = f"Scan stopped: {stopped}"[:300]
                progress_payload = _progress_counts(
                    entries, total=total, processed=processed
                )
                progress_payload["state"] = "finished"

            config_payload = dict(scan.scanner_config or {})
            config_payload.update(
                {
                    "scan_type": ScanType.AVWAP_PATTERN.value,
                    "scanner_version": PATTERN_SCANNER_VERSION,
                    "timeframe": timeframe,
                    "provider": "fyers",
                    "detector": config.to_dict(),
                    "execution": {
                        "started_at": started.isoformat(),
                        "finished_at": finished.isoformat(),
                        "duration_ms": int((finished - started).total_seconds() * 1000),
                        "matches": 0,
                        "fatal_error": stopped,
                    },
                }
            )
            if entries:
                config_payload["symbols"] = [dict(entry) for entry in entries]
            if progress_payload is not None:
                config_payload["progress"] = progress_payload
            scan.scanner_config = config_payload
            session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("pattern_scan_failure_persist_failed")
            session.rollback()
    finally:
        session.close()


def list_candidates(
    db: Session,
    *,
    scan_id: uuid.UUID | None = None,
    status: str | None = None,
    pattern_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[PatternCandidate], int]:
    stmt = select(PatternCandidate)
    count_stmt = select(func.count(PatternCandidate.id))
    conditions = []
    if scan_id:
        conditions.append(PatternCandidate.scan_id == scan_id)
    if status:
        conditions.append(PatternCandidate.status == status.upper())
    if pattern_type:
        conditions.append(PatternCandidate.pattern_type == pattern_type.upper())
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(PatternCandidate.pattern_end.desc(), PatternCandidate.symbol.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), int(total)


def candidates_for_scan(db: Session, scan_id: uuid.UUID) -> list[PatternCandidate]:
    rows = db.scalars(
        select(PatternCandidate)
        .where(PatternCandidate.scan_id == scan_id)
        .order_by(PatternCandidate.symbol.asc())
    ).all()
    return list(rows)


def pattern_summary(scan: ScanRun, candidates: Sequence[PatternCandidate]) -> dict[str, Any]:
    counts = {pattern_type: 0 for pattern_type in PATTERN_TYPES}
    for candidate in candidates:
        counts[candidate.pattern_type] = counts.get(candidate.pattern_type, 0) + 1
    execution = (scan.scanner_config or {}).get("execution", {}) or {}
    return {
        "timeframe": scan.timeframe,
        "matches": len(candidates),
        "instruments_resolved": execution.get("instruments_resolved", scan.total_symbols),
        "errors": len(execution.get("errors", []) or [])
        + len(execution.get("resolution_errors", []) or []),
        "classification_counts": counts,
    }


def pattern_symbols(scan: ScanRun) -> list[dict[str, Any]]:
    """Per-instrument progress rows recorded by the background job."""
    payload = scan.scanner_config or {}
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        return []
    return [dict(entry) for entry in symbols if isinstance(entry, dict)]


def pattern_progress(scan: ScanRun, *, matched: int | None = None) -> dict[str, Any]:
    """Progress snapshot for the admin progress bar.

    New runs store an authoritative snapshot in ``scanner_config``; runs that
    predate it fall back to the scan counters.
    """
    payload = scan.scanner_config or {}
    progress = payload.get("progress")
    if isinstance(progress, dict):
        total = int(progress.get("total") or scan.total_symbols or 0)
        processed = int(progress.get("processed") or 0)
        # Prefer the persisted candidate count when the caller supplies it, so
        # the progress bar can never disagree with the candidate list.
        matches = int(matched) if matched is not None else int(progress.get("matched") or 0)
        return {
            "state": progress.get("state") or "running",
            "processed": processed,
            "total": total,
            "percent": int(progress.get("percent") or 0),
            "matched": matches,
            "failed": int(progress.get("failed") or 0),
            "pending": int(progress.get("pending") or max(total - processed, 0)),
        }

    finished = scan.status in {
        ScanStatus.COMPLETED.value,
        ScanStatus.PARTIAL.value,
        ScanStatus.FAILED.value,
    }
    total = scan.total_symbols or 0
    processed = scan.successful_symbols + scan.failed_symbols if finished else 0
    if total:
        processed = min(processed, total)
    return {
        "state": "finished"
        if finished
        else ("queued" if scan.status == ScanStatus.PENDING.value else "running"),
        "processed": processed,
        "total": total,
        "percent": 100 if finished and total else 0,
        "matched": int(matched or 0),
        "failed": int(scan.failed_symbols or 0),
        "pending": max(total - processed, 0),
    }


def _get_candidate(db: Session, candidate_id: uuid.UUID) -> PatternCandidate:
    candidate = db.get(PatternCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Pattern candidate not found")
    return candidate


def approve_candidate(db: Session, candidate_id: uuid.UUID, user: User) -> PatternCandidate:
    candidate = _get_candidate(db, candidate_id)
    if candidate.status in {CandidateStatus.PUBLISHED.value, CandidateStatus.EXPIRED.value}:
        raise ConflictError("A published or expired pattern candidate cannot be approved")
    if candidate.status == CandidateStatus.APPROVED.value:
        return candidate
    previous = candidate.status
    candidate.status = CandidateStatus.APPROVED.value
    audit_service.record(
        db,
        action=AuditAction.CANDIDATE_APPROVED.value,
        entity_type="pattern_candidate",
        entity_id=str(candidate.id),
        details={
            "symbol": candidate.symbol,
            "pattern_type": candidate.pattern_type,
            "from": previous,
        },
        user=user,
    )
    db.commit()
    db.refresh(candidate)
    return candidate


def reject_candidate(
    db: Session,
    candidate_id: uuid.UUID,
    user: User,
    reason: str | None = None,
) -> PatternCandidate:
    candidate = _get_candidate(db, candidate_id)
    if candidate.status == CandidateStatus.PUBLISHED.value:
        raise ConflictError("A published pattern candidate cannot be rejected")
    if candidate.status == CandidateStatus.REJECTED.value:
        return candidate
    previous = candidate.status
    candidate.status = CandidateStatus.REJECTED.value
    audit_service.record(
        db,
        action=AuditAction.CANDIDATE_REJECTED.value,
        entity_type="pattern_candidate",
        entity_id=str(candidate.id),
        details={
            "symbol": candidate.symbol,
            "pattern_type": candidate.pattern_type,
            "from": previous,
            "reason": reason,
        },
        user=user,
    )
    db.commit()
    db.refresh(candidate)
    return candidate
