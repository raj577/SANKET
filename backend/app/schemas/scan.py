from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

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


class ScanDetailOut(ScanOut):
    scanner_config: dict | None = None
    warnings: list[str] = Field(default_factory=list)


class CandidateRejectRequest(ORMModel):
    reason: str | None = Field(default=None, max_length=1000)


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
