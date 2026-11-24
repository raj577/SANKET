from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ScanCreateRequest(ORMModel):
    scan_id: uuid.UUID | None = None
    started_at: datetime | None = None
    total_symbols: int = Field(default=0, ge=0)
    trigger: str | None = Field(default=None, max_length=32)


class ScanProgressRequest(ORMModel):
    current_symbol: str | None = Field(default=None, max_length=64)
    total_symbols: int | None = Field(default=None, ge=0)
    successful_symbols: int | None = Field(default=None, ge=0)
    failed_symbols: int | None = Field(default=None, ge=0)


class ScanCompleteRequest(ORMModel):
    status: str | None = None
    successful_symbols: int | None = Field(default=None, ge=0)
    failed_symbols: int | None = Field(default=None, ge=0)
    error_message: str | None = Field(default=None, max_length=4000)


class KotakScanRequest(ORMModel):
    symbols: list[str] | None = None
    depth: int = Field(default=5, ge=3, le=10)
    expiry: str | None = Field(default=None, max_length=10)
    provider: str | None = Field(default=None, max_length=16)


class PatternScanRequest(ORMModel):
    """Request for the independent AVWAP/VWAP pattern scanner.

    ``symbols`` accepts full FYERS symbols or bare underlyings. When omitted,
    the scanner uses the current-expiry NSE futures universe.
    """

    symbols: list[str] | None = None
    timeframe: str | None = Field(default=None, max_length=8)
    include_index: bool = True
    current_expiry_only: bool = True


class ScanCsvSummary(ORMModel):
    csv_filename: str | None = None
    csv_storage_path: str | None = None
    csv_size_bytes: int | None = None
    csv_checksum_sha256: str | None = None
    csv_saved_at: datetime | None = None


class ScanOut(ORMModel):
    id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    scan_type: str = "OI"
    timeframe: str | None = None
    total_symbols: int
    successful_symbols: int
    failed_symbols: int
    long_candidates_count: int
    short_candidates_count: int
    csv_filename: str | None
    csv_storage_path: str | None
    csv_size_bytes: int | None
    csv_saved_at: datetime | None
    csv_checksum_sha256: str | None
    scanner_version: str | None
    candidates_processed: bool
    last_progress_symbol: str | None
    trigger: str | None
    error_message: str | None
    created_at: datetime


class PatternCandidateOut(ORMModel):
    """One pattern detection. No confidence/score field exists by design."""

    id: uuid.UUID
    scan_id: uuid.UUID
    symbol: str
    underlying: str | None
    expiry: date | None
    timeframe: str
    pattern_type: str
    candle_count: int
    last_price: Decimal
    avwap: Decimal
    distance_pct: Decimal
    avg_body_ratio: Decimal
    max_body_ratio: Decimal
    window_range_pct: Decimal
    touched: bool
    atr: Decimal | None
    anchor_at: datetime | None
    pattern_start: datetime | None
    pattern_end: datetime | None
    status: str
    reason: str
    detector_metadata: dict | None
    created_at: datetime


class PatternSymbolOut(ORMModel):
    """One row of the live per-instrument progress list."""

    symbol: str
    underlying: str | None = None
    expiry: date | None = None
    status: str
    pattern_type: str | None = None
    message: str | None = None
    candles: int | None = None
    last_price: Decimal | None = None


class PatternProgressOut(ORMModel):
    state: str
    processed: int
    total: int
    percent: int
    matched: int
    failed: int
    pending: int


class ScanDetailOut(ScanOut):
    scanner_config: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    pattern_config: dict | None = None
    pattern_summary: dict | None = None
    pattern_candidates: list[PatternCandidateOut] = Field(default_factory=list)
    pattern_progress: PatternProgressOut | None = None
    pattern_symbols: list[PatternSymbolOut] = Field(default_factory=list)


class CandidateRejectRequest(ORMModel):
    reason: str | None = Field(default=None, max_length=1000)


class CandidateHistoryOut(BaseModel):
    """How a candidate relates to the scans that came before its own."""

    in_previous_scan: bool = False
    in_last_2_days: bool = False
    previous_direction: str | None = None
    short_to_long: bool = False
    previous_seen_at: datetime | None = None


class CandidateOut(ORMModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    symbol: str
    direction: str
    scan_ltp: Decimal
    score: Decimal
    grade: str
    reason: str
    confirmation_count: int
    scanned_at: datetime
    status: str
    created_at: datetime
    #: Filled by the list/detail endpoints; other responses leave it null.
    history: CandidateHistoryOut | None = None


class CandidateDetailOut(CandidateOut):
    signal_id: uuid.UUID | None = None
    scan_status: str | None = None


class CollectorStatusOut(ORMModel):
    server_time: datetime
    active_scans: int
    last_scan: ScanOut | None
    collector_authenticated: bool
    storage_backend: str
    scanner_version: str


class ArchiveOut(ORMModel):
    scan_id: uuid.UUID
    status: str
    started_at: datetime
    csv_filename: str | None
    csv_storage_path: str | None
    csv_size_bytes: int | None
    csv_checksum_sha256: str | None
    csv_saved_at: datetime | None
    download_url: str | None = None
