"""Schemas for the day-wise performance analysis of filtered candidates."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PerformanceOffsetOut(BaseModel):
    offset: int
    trade_date: date | None = None
    n: int
    avg_return_pct: float | None = None
    win_rate_pct: float | None = None
    best_return_pct: float | None = None
    worst_return_pct: float | None = None


class PerformanceSymbolOut(BaseModel):
    candidate_id: uuid.UUID
    scan_id: uuid.UUID
    symbol: str
    provider_symbol: str
    direction: str
    grade: str
    score: Decimal
    scan_ltp: Decimal
    scanned_at: datetime
    candidate_status: str
    #: COMPLETE | PARTIAL | PENDING | NO_DATA
    coverage: str
    closes: list[Decimal | None]
    returns_pct: list[float | None]


class PerformanceDayOut(BaseModel):
    day: date
    scans: int
    filtered: int
    long_count: int
    short_count: int
    duplicates_collapsed: int
    #: True when candles exist but no completed session follows this scan day.
    pending: bool = False
    offsets: list[PerformanceOffsetOut]
    symbols: list[PerformanceSymbolOut]


class PerformanceTotalsOut(BaseModel):
    filtered: int
    scan_days: int
    offsets: list[PerformanceOffsetOut]


class PerformanceCacheOut(BaseModel):
    data_from: date | None = None
    data_to: date | None = None
    candles: int = 0
    symbols: int = 0
    last_fetched_at: datetime | None = None


class PerformanceReportOut(BaseModel):
    date_from: date
    date_to: date
    forward_days: int
    #: all | approved | not_approved
    status_filter: str = "all"
    benchmark_symbol: str
    generated_at: datetime
    days: list[PerformanceDayOut]
    totals: PerformanceTotalsOut
    cache: PerformanceCacheOut
    #: Provider symbols used by the filtered list but absent from the cache.
    missing_symbols: list[str]
    #: Scan days with no completed forward session yet (for example today).
    pending_days: int


class CandleBackfillRequest(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    forward_days: int | None = Field(default=None, ge=1, le=30)
    symbols: list[str] | None = None


class CandleBackfillSymbolOut(BaseModel):
    symbol: str
    state: str
    candles: int = 0
    message: str | None = None


class CandleBackfillOut(BaseModel):
    run_id: uuid.UUID
    status: str
    #: queued | running | finished
    state: str
    range_from: date
    range_to: date
    started_at: datetime
    completed_at: datetime | None = None
    total_symbols: int
    processed_symbols: int
    failed_symbols: int
    candles_written: int
    percent: int
    fetched: int = 0
    no_data: int = 0
    pending: int = 0
    current: str | None = None
    error_message: str | None = None
    symbols: list[CandleBackfillSymbolOut] = []


__all__ = [
    "CandleBackfillOut",
    "CandleBackfillRequest",
    "CandleBackfillSymbolOut",
    "PerformanceCacheOut",
    "PerformanceDayOut",
    "PerformanceOffsetOut",
    "PerformanceReportOut",
    "PerformanceSymbolOut",
    "PerformanceTotalsOut",
]
