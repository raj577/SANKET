"""Daily candle cache and FYERS backfill for the performance analysis.

The OI scanner stores the spot at scan time but no forward prices. This module
fills that gap with completed **daily** spot candles for the underlyings the
scanner filtered, so the day-wise report never needs a live FYERS session while
someone is reading it.

Design notes
------------
* Only the cache table is written. No scan, candidate or signal row changes.
* FYERS daily history is paced (Standard plan: 50 requests/minute). A rate-limit
  answer is retried after a long pause instead of failing the symbol.
* An expired/invalid token aborts the job immediately and marks every remaining
  symbol ``ERROR`` with the reason, mirroring the pattern scanner.
* Progress is persisted per symbol so the admin progress bar survives a reload
  and a restart can mark the abandoned run as failed instead of "running".
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import IST, ensure_aware, utcnow
from app.market_data.errors import is_auth_error, is_rate_limit_error
from app.market_data.fyers_client import FyersClient, FyersError
from app.market_data.symbols import to_fyers_symbol
from app.models.market import CandleBackfillRun, InstrumentCandle
from app.scanner.patterns.candles import normalize_candles

logger = logging.getLogger("sensibull.candles")

STATE_PENDING = "PENDING"
STATE_FETCHING = "FETCHING"
STATE_FETCHED = "FETCHED"
STATE_NO_DATA = "NO_DATA"
STATE_ERROR = "ERROR"
STATE_SKIPPED = "SKIPPED"

#: States that make a symbol count as failed for the run counters.
FAILED_STATES = frozenset({STATE_ERROR, STATE_SKIPPED})

FINISHED_STATUSES = frozenset({"COMPLETED", "PARTIAL", "FAILED"})


def _decimal(value: Any, places: int = 4) -> Decimal:
    return Decimal(str(round(float(value), places)))


def _range_value(value: date) -> str:
    """Epoch seconds for IST midnight, which is what ``date_format="0"`` wants."""
    return str(int(datetime.combine(value, dt_time.min, tzinfo=IST).timestamp()))


class DailyCandleFetcher:
    """Chunked daily history retrieval with pacing and rate-limit backoff."""

    def __init__(
        self,
        client: FyersClient,
        *,
        pause_seconds: float = 1.3,
        chunk_days: int = 120,
        max_retries: int = 1,
        retry_pause_seconds: float = 0.5,
        rate_limit_backoff_seconds: float = 60.0,
        timezone: str = "Asia/Kolkata",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.pause_seconds = max(float(pause_seconds), 0.0)
        self.chunk_days = max(int(chunk_days), 1)
        self.max_retries = max(int(max_retries), 0)
        self.retry_pause_seconds = max(float(retry_pause_seconds), 0.0)
        self.rate_limit_backoff_seconds = max(float(rate_limit_backoff_seconds), 0.0)
        self.timezone = timezone
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.requests = 0

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        """Return normalized daily candles for ``start``..``end`` (inclusive)."""

        if start > end:
            return []
        rows: list[list[Any]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=self.chunk_days - 1), end)
            # Fold a one-day tail into the previous request: FYERS rejects a
            # chunk whose range_from equals range_to.
            if 0 < (end - chunk_end).days <= 1:
                chunk_end = end
            payload = self._request(symbol, cursor, chunk_end)
            candles = payload.get("candles") if isinstance(payload, dict) else None
            if candles:
                if not isinstance(candles, list):
                    raise FyersError(f"Malformed candles returned for {symbol}.")
                rows.extend(candles)
            cursor = chunk_end + timedelta(days=1)

        if not rows:
            return []

        frame = normalize_candles(rows, self.timezone)
        if frame.empty:
            return []
        result: list[dict[str, Any]] = []
        for record in frame.itertuples(index=False):
            trade_date = record.timestamp.date()
            if trade_date < start or trade_date > end:
                continue
            result.append(
                {
                    "trade_date": trade_date,
                    "open": _decimal(record.open),
                    "high": _decimal(record.high),
                    "low": _decimal(record.low),
                    "close": _decimal(record.close),
                    "volume": round(float(record.volume or 0)),
                }
            )
        return result

    def _wait_for_slot(self) -> None:
        if self.pause_seconds <= 0:
            return
        now = self._clock()
        if self._last_request_at is not None:
            wait = self.pause_seconds - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _request(self, symbol: str, start: date, end: date) -> dict:
        last_error: FyersError | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_for_slot()
            self.requests += 1
            try:
                return self.client.history(
                    symbol,
                    resolution="D",
                    range_from=_range_value(start),
                    range_to=_range_value(end),
                    date_format="0",
                    cont_flag="0",
                )
            except FyersError as exc:
                last_error = exc
                if is_auth_error(exc) or attempt >= self.max_retries:
                    raise
                pause = (
                    self.rate_limit_backoff_seconds
                    if is_rate_limit_error(exc)
                    else self.retry_pause_seconds
                )
                logger.warning(
                    "Daily history failed for %s (attempt %s/%s, retrying in %.1fs): %s",
                    symbol,
                    attempt + 1,
                    self.max_retries + 1,
                    pause,
                    exc,
                )
                if pause:
                    self._sleep(pause)
        assert last_error is not None
        raise last_error


def upsert_candles(
    db: Session, symbol: str, candles: Iterable[dict[str, Any]]
) -> int:
    """Insert new candles and refresh changed values for existing dates.

    Updating matters: a candle fetched while the session was still open is a
    partial day, and the next refresh must replace it with the final close.
    """

    payload = {candle["trade_date"]: candle for candle in candles}
    if not payload:
        return 0
    existing = {
        row.trade_date: row
        for row in db.scalars(
            select(InstrumentCandle).where(
                InstrumentCandle.symbol == symbol,
                InstrumentCandle.trade_date.in_(list(payload)),
            )
        ).all()
    }
    written = 0
    fetched_at = utcnow()
    for trade_date, candle in sorted(payload.items()):
        row = existing.get(trade_date)
        if row is None:
            db.add(
                InstrumentCandle(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    source="FYERS",
                    fetched_at=fetched_at,
                )
            )
            written += 1
            continue
        changed = (
            row.open != candle["open"]
            or row.high != candle["high"]
            or row.low != candle["low"]
            or row.close != candle["close"]
            or row.volume != candle["volume"]
        )
        row.open = candle["open"]
        row.high = candle["high"]
        row.low = candle["low"]
        row.close = candle["close"]
        row.volume = candle["volume"]
        row.fetched_at = fetched_at
        if changed:
            written += 1
    db.commit()
    return written


def candle_coverage(db: Session) -> dict[str, Any]:
    """What the cache currently contains, for the admin coverage banner."""

    row = db.execute(
        select(
            func.min(InstrumentCandle.trade_date),
            func.max(InstrumentCandle.trade_date),
            func.count(InstrumentCandle.id),
            func.count(func.distinct(InstrumentCandle.symbol)),
            func.max(InstrumentCandle.fetched_at),
        )
    ).one()
    data_from, data_to, candles, symbols, fetched_at = row
    return {
        "data_from": data_from,
        "data_to": data_to,
        "candles": int(candles or 0),
        "symbols": int(symbols or 0),
        "last_fetched_at": ensure_aware(fetched_at) if fetched_at else None,
    }


def normalize_symbols(symbols: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        text = str(raw or "").strip().upper()
        if not text:
            continue
        provider_symbol = to_fyers_symbol(text)
        if provider_symbol in seen:
            continue
        seen.add(provider_symbol)
        cleaned.append(provider_symbol)
    return sorted(cleaned)


def _entry(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "state": STATE_PENDING,
        "candles": 0,
        "message": None,
    }


def _progress(
    entries: Sequence[dict[str, Any]],
    processed: int,
    *,
    state: str,
    current: str | None = None,
) -> dict[str, Any]:
    total = len(entries)
    fetched = sum(1 for entry in entries if entry["state"] == STATE_FETCHED)
    no_data = sum(1 for entry in entries if entry["state"] == STATE_NO_DATA)
    failed = sum(1 for entry in entries if entry["state"] in FAILED_STATES)
    return {
        "state": state,
        "processed": processed,
        "total": total,
        "percent": 100 if total and processed >= total else int(processed / total * 100) if total else 0,
        "fetched": fetched,
        "no_data": no_data,
        "failed": failed,
        "pending": max(total - processed, 0),
        "current": current,
        "symbols": [dict(entry) for entry in entries],
    }


def _save_progress(
    db: Session,
    job: CandleBackfillRun,
    entries: Sequence[dict[str, Any]],
    processed: int,
    *,
    state: str,
    current: str | None = None,
    candles_written: int | None = None,
) -> None:
    job.progress = _progress(entries, processed, state=state, current=current)
    job.processed_symbols = processed
    job.failed_symbols = sum(1 for entry in entries if entry["state"] in FAILED_STATES)
    if candles_written is not None:
        job.candles_written = candles_written
    db.commit()


def mark_stale_runs_failed(db: Session, *, older_than_minutes: int | None = None) -> int:
    """Close runs left RUNNING by a restart so they stop blocking new ones."""

    settings = get_settings()
    minutes = (
        settings.performance_stale_run_minutes
        if older_than_minutes is None
        else max(int(older_than_minutes), 0)
    )
    cutoff = utcnow() - timedelta(minutes=minutes)
    stale = [
        job
        for job in db.scalars(
            select(CandleBackfillRun).where(CandleBackfillRun.status == "RUNNING")
        ).all()
        if ensure_aware(job.updated_at) < cutoff
    ]
    for job in stale:
        payload = dict(job.progress or {})
        entries = [dict(entry) for entry in payload.get("symbols", [])]
        for entry in entries:
            if entry.get("state") in {STATE_PENDING, STATE_FETCHING}:
                entry["state"] = STATE_ERROR
                entry["message"] = (
                    "Backfill stopped: the job did not finish (server restart or timeout)"
                )
        job.status = "FAILED"
        job.completed_at = utcnow()
        job.error_message = (
            job.error_message
            or "Backfill stopped: the job did not finish (server restart or timeout)"
        )
        payload.update(_progress(entries, job.processed_symbols, state="finished"))
        job.progress = payload
        job.failed_symbols = sum(
            1 for entry in entries if entry["state"] in FAILED_STATES
        )
    if stale:
        db.commit()
    return len(stale)


def get_run(db: Session, run_id) -> CandleBackfillRun:
    job = db.get(CandleBackfillRun, run_id)
    if job is None:
        raise NotFoundError("Candle backfill run not found")
    return job


def latest_run(db: Session) -> CandleBackfillRun | None:
    return db.scalars(
        select(CandleBackfillRun).order_by(CandleBackfillRun.started_at.desc()).limit(1)
    ).first()


def active_run(db: Session) -> CandleBackfillRun | None:
    return db.scalars(
        select(CandleBackfillRun)
        .where(CandleBackfillRun.status.in_(("PENDING", "RUNNING")))
        .order_by(CandleBackfillRun.started_at.desc())
        .limit(1)
    ).first()


def create_backfill(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    symbols: Sequence[str],
) -> CandleBackfillRun:
    settings = get_settings()
    if date_from > date_to:
        raise ValidationError("date_from must be on or before date_to")
    if (date_to - date_from).days > 365:
        raise ValidationError("Backfill range is limited to 366 days")

    mark_stale_runs_failed(db)
    running = active_run(db)
    if running is not None:
        raise ConflictError(
            "A candle backfill is already running; wait for it before starting another"
        )

    cleaned = normalize_symbols(symbols)
    if not cleaned:
        raise ValidationError(
            "No symbols to fetch; run an OI scan first or widen the date range"
        )
    if len(cleaned) > settings.performance_max_symbols_per_run:
        raise ValidationError(
            f"At most {settings.performance_max_symbols_per_run} symbols can be refreshed "
            "per run; narrow the date range"
        )

    job = CandleBackfillRun(
        status="PENDING",
        range_from=date_from,
        range_to=date_to,
        total_symbols=len(cleaned),
        processed_symbols=0,
        failed_symbols=0,
        candles_written=0,
        progress=_progress([_entry(symbol) for symbol in cleaned], 0, state="queued"),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def progress_out(job: CandleBackfillRun) -> dict[str, Any]:
    payload = dict(job.progress or {})
    if not payload:
        payload = _progress([], job.processed_symbols or 0, state="queued")
    payload.setdefault("state", "queued" if job.status == "PENDING" else "running")
    if job.status in FINISHED_STATUSES:
        payload["state"] = "finished"
    payload["run_id"] = str(job.id)
    payload["status"] = job.status
    payload["range_from"] = job.range_from
    payload["range_to"] = job.range_to
    payload["started_at"] = ensure_aware(job.started_at)
    payload["completed_at"] = ensure_aware(job.completed_at) if job.completed_at else None
    payload["total_symbols"] = job.total_symbols
    payload["processed_symbols"] = job.processed_symbols
    payload["failed_symbols"] = job.failed_symbols
    payload["candles_written"] = job.candles_written
    payload["error_message"] = job.error_message
    return payload


def _build_fetcher() -> DailyCandleFetcher:
    settings = get_settings()
    return DailyCandleFetcher(
        FyersClient(),
        pause_seconds=settings.performance_history_pause_seconds,
        chunk_days=settings.performance_history_chunk_days,
        rate_limit_backoff_seconds=settings.performance_rate_limit_backoff_seconds,
        timezone=settings.timezone,
    )


def run_backfill_job(
    run_id,
    symbols: Sequence[str],
    *,
    fetcher: DailyCandleFetcher | None = None,
) -> None:
    """Background job: fetch and cache daily candles for every symbol."""

    from app.db.session import get_sessionmaker

    session = get_sessionmaker()()
    job: CandleBackfillRun | None = None
    owns_fetcher = fetcher is None
    entries: list[dict[str, Any]] = []
    processed = 0
    written = 0
    try:
        job = session.get(CandleBackfillRun, run_id)
        if job is None:
            logger.warning("candle_backfill_missing", extra={"run_id": str(run_id)})
            return

        job.status = "RUNNING"
        job.started_at = utcnow()
        entries = [_entry(symbol) for symbol in symbols]
        job.total_symbols = len(entries)
        _save_progress(
            session,
            job,
            entries,
            0,
            state="running",
            current=entries[0]["symbol"] if entries else None,
        )

        if fetcher is None:
            fetcher = _build_fetcher()

        for index, symbol in enumerate(symbols):
            entry = entries[index]
            entry["state"] = STATE_FETCHING
            _save_progress(session, job, entries, processed, state="running", current=symbol)
            try:
                candles = fetcher.fetch(symbol, job.range_from, job.range_to)
                if candles:
                    written += upsert_candles(session, symbol, candles)
                    entry["state"] = STATE_FETCHED
                    entry["candles"] = len(candles)
                else:
                    entry["state"] = STATE_NO_DATA
                    entry["message"] = "FYERS returned no daily candles in this range"
            except FyersError as exc:
                session.rollback()
                if is_auth_error(exc):
                    raise
                entry["state"] = STATE_ERROR
                entry["message"] = str(exc)[:300]
                logger.warning(
                    "candle_backfill_symbol_failed",
                    extra={"run_id": str(run_id), "symbol": symbol, "error": str(exc)},
                )
            processed = index + 1
            job.candles_written = written
            _save_progress(
                session, job, entries, processed, state="running", current=None
            )

        failed = sum(1 for entry in entries if entry["state"] in FAILED_STATES)
        fetched = sum(1 for entry in entries if entry["state"] == STATE_FETCHED)
        if failed == 0:
            job.status = "COMPLETED"
        elif fetched or any(entry["state"] == STATE_NO_DATA for entry in entries):
            job.status = "PARTIAL"
        else:
            job.status = "FAILED"
        job.completed_at = utcnow()
        job.error_message = (
            "; ".join(
                f"{entry['symbol']}: {entry['message']}"
                for entry in entries
                if entry["state"] in FAILED_STATES and entry["message"]
            )[:4000]
            or None
        )
        _save_progress(session, job, entries, processed, state="finished", candles_written=written)
        logger.info(
            "candle_backfill_complete",
            extra={
                "run_id": str(run_id),
                "status": job.status,
                "fetched": fetched,
                "failed": failed,
                "candles": written,
            },
        )
    except Exception as exc:
        logger.exception("candle_backfill_failed", extra={"run_id": str(run_id)})
        session.rollback()
        try:
            job = session.get(CandleBackfillRun, run_id)
            if job is None:
                return
            stopped = str(exc) or type(exc).__name__
            for entry in entries:
                if entry["state"] in {STATE_PENDING, STATE_FETCHING}:
                    entry["state"] = STATE_ERROR
                    entry["message"] = f"Backfill stopped: {stopped}"[:300]
            job.status = "FAILED"
            job.completed_at = utcnow()
            job.error_message = stopped[:4000]
            _save_progress(session, job, entries, processed, state="finished")
        except Exception:
            logger.exception("candle_backfill_failure_persist_failed")
            session.rollback()
    finally:
        if owns_fetcher and fetcher is not None:
            fetcher.close()
        session.close()


__all__ = [
    "FINISHED_STATUSES",
    "STATE_ERROR",
    "STATE_FETCHED",
    "STATE_FETCHING",
    "STATE_NO_DATA",
    "STATE_PENDING",
    "STATE_SKIPPED",
    "DailyCandleFetcher",
    "active_run",
    "candle_coverage",
    "create_backfill",
    "get_run",
    "latest_run",
    "mark_stale_runs_failed",
    "normalize_symbols",
    "progress_out",
    "run_backfill_job",
    "upsert_candles",
]
