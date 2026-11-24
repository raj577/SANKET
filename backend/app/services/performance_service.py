"""Day-wise performance of the OI scanner's filtered candidates.

A "filtered stock" is one row of ``scan_candidates``: the OI scanner already
kept only the underlyings that passed its filters. For every scan day this
module computes how the underlying moved, in the direction the scanner picked,
from ``scan_ltp`` to the close of each following trading day.

Prices come exclusively from the ``instrument_candles`` cache, so the report is
fast, repeatable, and unaffected by an expired FYERS token. Only **completed**
sessions count: today's still-forming candle is excluded.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.core.timeutils import ist_day_bounds_utc, to_ist, utcnow
from app.market_data.symbols import to_fyers_symbol
from app.models.enums import CandidateStatus, Direction, ScanType
from app.models.market import InstrumentCandle
from app.models.scan import ScanCandidate, ScanRun
from app.services import candle_service

COVERAGE_COMPLETE = "COMPLETE"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_PENDING = "PENDING"
COVERAGE_NO_DATA = "NO_DATA"

#: Stock-set filters for the report. "approved" covers a candidate the reviewer
#: accepted (and one that later expired); "not_approved" covers the rest, i.e.
#: still waiting for review or explicitly rejected.
STATUS_FILTER_ALL = "all"
STATUS_FILTER_APPROVED = "approved"
STATUS_FILTER_NOT_APPROVED = "not_approved"
STATUS_FILTERS = (
    STATUS_FILTER_ALL,
    STATUS_FILTER_APPROVED,
    STATUS_FILTER_NOT_APPROVED,
)
_APPROVED_STATUSES = frozenset(
    {
        CandidateStatus.APPROVED.value,
        CandidateStatus.PUBLISHED.value,
        CandidateStatus.EXPIRED.value,
    }
)
_NOT_APPROVED_STATUSES = frozenset(
    {CandidateStatus.PENDING.value, CandidateStatus.REJECTED.value}
)
_STATUS_FILTER_SETS: dict[str, frozenset[str]] = {
    STATUS_FILTER_APPROVED: _APPROVED_STATUSES,
    STATUS_FILTER_NOT_APPROVED: _NOT_APPROVED_STATUSES,
}

#: Extra calendar days fetched beyond the end of the window so D+N closes exist
#: even across weekends and holidays.
FORWARD_BUFFER_DAYS = 14


def _direction_sign(direction: str) -> int:
    return 1 if str(direction).upper() == Direction.LONG.value else -1


def _return_pct(entry: Any, close: Any, sign: int) -> float | None:
    if close is None:
        return None
    try:
        entry_value = Decimal(str(entry))
        close_value = Decimal(str(close))
    except (ArithmeticError, TypeError, ValueError):
        # A malformed stored price must not take down the whole report.
        return None
    if entry_value <= 0:
        return None
    return round(float((close_value - entry_value) / entry_value * 100) * sign, 2)


def today_ist(now: datetime | None = None) -> date:
    return to_ist(now or utcnow()).date()


def resolve_forward_days(value: int | None) -> int:
    settings = get_settings()
    days = settings.performance_forward_days if value is None else int(value)
    if days < 1 or days > settings.performance_max_forward_days:
        raise ValidationError(
            f"forward_days must be between 1 and {settings.performance_max_forward_days}"
        )
    return days


def resolve_status_filter(value: str | None) -> str:
    """Normalise the stock-set filter, rejecting unknown values."""
    choice = (value or STATUS_FILTER_ALL).strip().lower()
    if choice not in STATUS_FILTERS:
        allowed = ", ".join(STATUS_FILTERS)
        raise ValidationError(f"status must be one of: {allowed}")
    return choice


def _candidates_in_window(
    db: Session, date_from: date, date_to: date, *, status_filter: str = STATUS_FILTER_ALL
) -> list[tuple[ScanCandidate, ScanRun]]:
    start, _ = ist_day_bounds_utc(date_from)
    _, end = ist_day_bounds_utc(date_to)
    statement = (
        select(ScanCandidate, ScanRun)
        .join(ScanRun, ScanCandidate.scan_id == ScanRun.id)
        .where(ScanRun.scan_type == ScanType.OI.value)
        .where(ScanCandidate.scanned_at >= start)
        .where(ScanCandidate.scanned_at < end)
        .order_by(ScanCandidate.scanned_at.asc())
    )
    statuses = _STATUS_FILTER_SETS.get(status_filter)
    if statuses is not None:
        statement = statement.where(ScanCandidate.status.in_(statuses))
    rows = db.execute(statement).all()
    return [(candidate, scan) for candidate, scan in rows]


def symbols_for_range(db: Session, date_from: date, date_to: date) -> list[str]:
    """Provider symbols that need candles for this window, plus the benchmark.

    The benchmark index is always included: its dates define the trading
    calendar, so a candidate that did not trade on a given day cannot shift
    everybody else's D+1.
    """

    settings = get_settings()
    symbols = {
        to_fyers_symbol(candidate.symbol)
        for candidate, _ in _candidates_in_window(db, date_from, date_to)
    }
    symbols.add(settings.performance_benchmark_symbol)
    return sorted(symbols)


def default_range(db: Session, *, now: datetime | None = None) -> tuple[date, date]:
    settings = get_settings()
    end = today_ist(now)
    earliest = db.scalar(select(func.min(ScanCandidate.scanned_at)))
    start = to_ist(earliest).date() if earliest is not None else end - timedelta(
        days=settings.performance_default_lookback_days
    )
    return start, end


def refresh_window(
    date_from: date, date_to: date, forward_days: int, *, now: datetime | None = None
) -> tuple[date, date]:
    """Candle dates needed for the report: the window plus forward buffer."""

    end = min(
        today_ist(now),
        date_to + timedelta(days=forward_days * 2 + FORWARD_BUFFER_DAYS),
    )
    return date_from, max(end, date_to)


def _load_candles(
    db: Session, date_from: date, date_to: date
) -> dict[str, dict[date, Decimal]]:
    rows = db.execute(
        select(
            InstrumentCandle.symbol,
            InstrumentCandle.trade_date,
            InstrumentCandle.close,
        )
        .where(InstrumentCandle.trade_date >= date_from)
        .where(InstrumentCandle.trade_date <= date_to)
        .order_by(InstrumentCandle.trade_date.asc())
    ).all()

    by_symbol: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for symbol, trade_date, close in rows:
        by_symbol[symbol][trade_date] = close
    return by_symbol


def _build_calendar(by_symbol: dict[str, dict[date, Decimal]], *, today: date) -> list[date]:
    settings = get_settings()
    benchmark = by_symbol.get(settings.performance_benchmark_symbol) or {}
    dates = set(benchmark)
    if not dates:
        for symbol_dates in by_symbol.values():
            dates.update(symbol_dates)
    # Only completed sessions can be used for forward returns.
    return sorted(day for day in dates if day < today)


def _symbol_coverage(
    candles: dict[date, Decimal], offset_dates: Sequence[date]
) -> str:
    if not candles:
        return COVERAGE_NO_DATA
    if not offset_dates:
        return COVERAGE_PENDING
    present = sum(1 for day in offset_dates if day in candles)
    if present == len(offset_dates):
        return COVERAGE_COMPLETE
    if present == 0:
        return COVERAGE_NO_DATA
    return COVERAGE_PARTIAL


def _offset_stats(
    offset: int, trade_date: date | None, values: Iterable[float | None]
) -> dict[str, Any]:
    cleaned = [value for value in values if value is not None]
    base: dict[str, Any] = {
        "offset": offset,
        "trade_date": trade_date,
        "n": 0,
        "avg_return_pct": None,
        "win_rate_pct": None,
        "best_return_pct": None,
        "worst_return_pct": None,
    }
    if not cleaned:
        return base
    wins = sum(1 for value in cleaned if value > 0)
    base.update(
        {
            "n": len(cleaned),
            "avg_return_pct": round(sum(cleaned) / len(cleaned), 2),
            "win_rate_pct": round(wins / len(cleaned) * 100, 1),
            "best_return_pct": max(cleaned),
            "worst_return_pct": min(cleaned),
        }
    )
    return base


def _awaiting_forward_session(
    day: date,
    offset_dates: Sequence[date],
    *,
    latest_session: date | None,
    has_cache: bool,
) -> bool:
    """True when candles exist but no completed session follows ``day`` yet.

    An empty cache is *not* pending: that means the backfill has not run, and
    the report already lists those symbols in ``missing_symbols``.
    """

    if offset_dates or not has_cache:
        return False
    return latest_session is None or day >= latest_session


def build_report(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    forward_days: int | None = None,
    status_filter: str | None = None,
    include_symbols: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if date_from > date_to:
        raise ValidationError("date_from must be on or before date_to")
    if (date_to - date_from).days > 366:
        raise ValidationError("The performance window is limited to 366 days")

    forward = resolve_forward_days(forward_days)
    chosen_status = resolve_status_filter(status_filter)
    current_day = today_ist(now)
    candidates = _candidates_in_window(
        db, date_from, date_to, status_filter=chosen_status
    )

    candle_end = min(
        current_day, date_to + timedelta(days=forward * 2 + FORWARD_BUFFER_DAYS)
    )
    by_symbol = _load_candles(db, date_from, candle_end)
    calendar = _build_calendar(by_symbol, today=current_day)
    latest_session = calendar[-1] if calendar else None
    has_cache = bool(by_symbol)

    # One row per stock per scan day: repeated scans of the same symbol would
    # otherwise double-count the day. The most recent scan wins.
    grouped: dict[date, dict[str, tuple[ScanCandidate, ScanRun]]] = defaultdict(dict)
    duplicates: dict[date, int] = defaultdict(int)
    for candidate, scan in candidates:
        day = to_ist(candidate.scanned_at).date()
        symbol = str(candidate.symbol or "").strip().upper()
        if not symbol:
            continue
        if symbol in grouped[day]:
            duplicates[day] += 1
        grouped[day][symbol] = (candidate, scan)

    missing_symbols: set[str] = set()
    days: list[dict[str, Any]] = []
    pooled: dict[int, list[float]] = defaultdict(list)
    total_filtered = 0

    for day in sorted(grouped):
        stock_rows = grouped[day]
        offset_dates = [trade_date for trade_date in calendar if trade_date > day][:forward]
        values_by_offset: list[list[float | None]] = [[] for _ in offset_dates]
        symbol_payloads: list[dict[str, Any]] = []
        long_count = 0
        short_count = 0

        for symbol, (candidate, scan) in sorted(stock_rows.items()):
            provider_symbol = to_fyers_symbol(symbol)
            candles = by_symbol.get(provider_symbol, {})
            if not candles:
                missing_symbols.add(provider_symbol)
            sign = _direction_sign(candidate.direction)
            closes = [candles.get(trade_date) for trade_date in offset_dates]
            returns = [
                _return_pct(candidate.scan_ltp, close, sign) for close in closes
            ]
            for index, value in enumerate(returns):
                values_by_offset[index].append(value)
                if value is not None:
                    pooled[index].append(value)
            if str(candidate.direction).upper() == Direction.LONG.value:
                long_count += 1
            else:
                short_count += 1

            if include_symbols:
                symbol_payloads.append(
                    {
                        "candidate_id": candidate.id,
                        "scan_id": candidate.scan_id,
                        "symbol": symbol,
                        "provider_symbol": provider_symbol,
                        "direction": candidate.direction,
                        "grade": candidate.grade,
                        "score": candidate.score,
                        "scan_ltp": candidate.scan_ltp,
                        "scanned_at": candidate.scanned_at,
                        "candidate_status": candidate.status,
                        "coverage": _symbol_coverage(candles, offset_dates),
                        "closes": closes,
                        "returns_pct": returns,
                    }
                )

        total_filtered += len(stock_rows)
        days.append(
            {
                "day": day,
                "scans": len({scan.id for _candidate, scan in stock_rows.values()}),
                "filtered": len(stock_rows),
                "long_count": long_count,
                "short_count": short_count,
                "duplicates_collapsed": duplicates[day],
                "pending": _awaiting_forward_session(
                    day,
                    offset_dates,
                    latest_session=latest_session,
                    has_cache=has_cache,
                ),
                "offsets": [
                    _offset_stats(index + 1, trade_date, values_by_offset[index])
                    for index, trade_date in enumerate(offset_dates)
                ],
                "symbols": symbol_payloads,
            }
        )

    totals_offsets = [
        _offset_stats(index + 1, None, pooled[index]) for index in range(forward)
    ]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "forward_days": forward,
        "status_filter": chosen_status,
        "benchmark_symbol": settings.performance_benchmark_symbol,
        "generated_at": utcnow(),
        "days": days,
        "totals": {
            "filtered": total_filtered,
            "scan_days": len(days),
            "offsets": totals_offsets,
        },
        "cache": candle_service.candle_coverage(db),
        "missing_symbols": sorted(missing_symbols),
        "pending_days": sum(1 for day in days if day["pending"]),
    }


__all__ = [
    "COVERAGE_COMPLETE",
    "COVERAGE_NO_DATA",
    "COVERAGE_PARTIAL",
    "COVERAGE_PENDING",
    "STATUS_FILTERS",
    "STATUS_FILTER_ALL",
    "STATUS_FILTER_APPROVED",
    "STATUS_FILTER_NOT_APPROVED",
    "build_report",
    "default_range",
    "refresh_window",
    "resolve_forward_days",
    "resolve_status_filter",
    "symbols_for_range",
    "today_ist",
]
