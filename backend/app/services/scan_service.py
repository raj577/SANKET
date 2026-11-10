"""Scan lifecycle: creation, progress, CSV ingestion, scanning and completion."""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, StorageError, ValidationError
from app.core.logging import get_logger
from app.core.timeutils import ensure_aware, utcnow
from app.models.enums import CandidateStatus, ScanStatus
from app.models.scan import ScanCandidate, ScanRun
from app.scanner.engine import ScanResult, scan_dataframe
from app.scanner.scoring import ScannerConfig
from app.services import settings_service
from app.services.csv_storage import get_storage
from app.services.notification_service import notify_scan_failed

logger = get_logger(__name__)


def create_scan(
    db: Session,
    *,
    scan_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
    total_symbols: int = 0,
    trigger: str | None = None,
) -> ScanRun:
    if scan_id is not None:
        existing = db.get(ScanRun, scan_id)
        if existing is not None:
            return existing

    scan = ScanRun(
        id=scan_id or uuid.uuid4(),
        started_at=ensure_aware(started_at) if started_at else utcnow(),
        status=ScanStatus.PENDING.value,
        total_symbols=max(int(total_symbols or 0), 0),
        trigger=trigger,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def get_scan(db: Session, scan_id: uuid.UUID) -> ScanRun:
    scan = db.get(ScanRun, scan_id)
    if scan is None:
        raise NotFoundError("Scan not found")
    return scan


def record_progress(
    db: Session,
    scan: ScanRun,
    *,
    current_symbol: str | None = None,
    total_symbols: int | None = None,
    successful_symbols: int | None = None,
    failed_symbols: int | None = None,
) -> ScanRun:
    if scan.status in {ScanStatus.COMPLETED.value, ScanStatus.PARTIAL.value, ScanStatus.FAILED.value}:
        return scan
    if scan.status == ScanStatus.PENDING.value:
        scan.status = ScanStatus.RUNNING.value
    if current_symbol is not None:
        scan.last_progress_symbol = current_symbol[:64]
    if total_symbols is not None:
        scan.total_symbols = max(int(total_symbols), 0)
    if successful_symbols is not None:
        scan.successful_symbols = max(int(successful_symbols), 0)
    if failed_symbols is not None:
        scan.failed_symbols = max(int(failed_symbols), 0)
    db.commit()
    db.refresh(scan)
    return scan


def _validate_csv_header(content: bytes) -> None:
    if not content:
        raise ValidationError("Uploaded CSV is empty")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must be valid UTF-8 text") from exc
    header = text.splitlines()[0] if text.splitlines() else ""
    columns = [column.strip() for column in header.split(",")]
    if "Symbol" not in columns:
        raise ValidationError("CSV header is missing the Symbol column")
    if "Spot" not in columns:
        raise ValidationError("CSV header is missing the Spot column")


def _persist_candidates(
    db: Session, scan: ScanRun, result: ScanResult, scanned_at: datetime
) -> tuple[int, int]:
    # A multi-day scan concatenates one CSV per date, so the same symbol can
    # appear more than once. Keep the last observation per symbol/direction;
    # the database enforces one candidate per scan/symbol/direction.
    deduped: dict[tuple[str, str], object] = {}
    for candidate in [*result.longs, *result.shorts]:
        deduped[(candidate.symbol[:32], candidate.direction)] = candidate

    for candidate in deduped.values():
        db.add(
            ScanCandidate(
                scan_id=scan.id,
                symbol=candidate.symbol[:32],
                direction=candidate.direction,
                scan_ltp=candidate.scan_ltp,
                score=candidate.score,
                grade=candidate.grade,
                reason=candidate.reason,
                confirmation_count=candidate.confirmation_count,
                scanned_at=ensure_aware(scanned_at),
                status=CandidateStatus.PENDING.value,
            )
        )

    long_count = sum(1 for item in deduped.values() if item.direction == "LONG")
    short_count = sum(1 for item in deduped.values() if item.direction == "SHORT")
    return long_count, short_count


def handle_csv_upload(
    db: Session,
    scan: ScanRun,
    *,
    content: bytes,
    total_symbols: int | None = None,
    successful_symbols: int | None = None,
    failed_symbols: int | None = None,
) -> ScanRun:
    import hashlib

    settings = get_settings()
    if len(content) > settings.storage_max_csv_bytes:
        raise ValidationError(
            f"CSV exceeds the {settings.storage_max_csv_bytes} byte upload limit"
        )

    checksum = hashlib.sha256(content).hexdigest()
    if scan.csv_saved_at is not None:
        if scan.csv_checksum_sha256 == checksum:
            return scan
        raise ConflictError("A different CSV has already been uploaded for this scan")

    if scan.status == ScanStatus.FAILED.value:
        raise ConflictError("Cannot upload a CSV for a failed scan")

    _validate_csv_header(content)

    if total_symbols is not None:
        scan.total_symbols = max(int(total_symbols), 0)
    if successful_symbols is not None:
        scan.successful_symbols = max(int(successful_symbols), 0)
    if failed_symbols is not None:
        scan.failed_symbols = max(int(failed_symbols), 0)
    if scan.total_symbols == 0:
        scan.total_symbols = scan.successful_symbols + scan.failed_symbols

    # 1) Archive first so the original CSV is never lost, even if scanning fails.
    try:
        stored = get_storage().save_csv(content, scan.started_at, scan.id)
    except StorageError as exc:
        scan.status = ScanStatus.FAILED.value
        scan.error_message = f"CSV storage failed: {exc.message}"
        scan.completed_at = utcnow()
        db.commit()
        notify_scan_failed(scan.id, scan.error_message)
        raise

    scan.csv_filename = stored.filename
    scan.csv_storage_path = stored.relative_path
    scan.csv_size_bytes = stored.size_bytes
    scan.csv_checksum_sha256 = stored.checksum_sha256
    scan.csv_saved_at = utcnow()
    scan.status = ScanStatus.RUNNING.value
    db.commit()

    # 2) Scan the archived CSV with the versioned configuration.
    scanner_settings = settings_service.get_value(db, "scanner")
    if not bool(scanner_settings.get("enabled", True)):
        scan.status = ScanStatus.PARTIAL.value
        scan.candidates_processed = True
        scan.completed_at = utcnow()
        scan.error_message = (
            "Scanner disabled in settings; CSV archived without candidate extraction."
        )
        db.commit()
        db.refresh(scan)
        return scan

    config: ScannerConfig = settings_service.scanner_config_from_settings(db)
    try:
        frame = pd.read_csv(io.BytesIO(content))
        result = scan_dataframe(frame, config)
        long_count, short_count = _persist_candidates(db, scan, result, scan.started_at)

        scan.long_candidates_count = long_count
        scan.short_candidates_count = short_count
        scan.scanner_version = result.config_version
        scan.scanner_config = result.config
        scan.candidates_processed = True
        scan.status = (
            ScanStatus.PARTIAL.value
            if scan.failed_symbols > 0 or result.warnings
            else ScanStatus.COMPLETED.value
        )
        scan.completed_at = utcnow()
        scan.error_message = "; ".join(result.warnings) if result.warnings else None
        db.commit()
        db.refresh(scan)
        return scan
    except Exception as exc:  # noqa: BLE001 - archive is already safe; record failure
        db.rollback()
        scan = db.get(ScanRun, scan.id)
        assert scan is not None
        scan.status = ScanStatus.FAILED.value
        scan.error_message = f"Scanner failed: {exc}"
        scan.completed_at = utcnow()
        db.commit()
        logger.exception("scan_processing_failed", extra={"scan_id": str(scan.id)})
        notify_scan_failed(scan.id, scan.error_message)
        db.refresh(scan)
        return scan


def complete_scan(
    db: Session,
    scan: ScanRun,
    *,
    status: str | None = None,
    successful_symbols: int | None = None,
    failed_symbols: int | None = None,
    error_message: str | None = None,
) -> ScanRun:
    if successful_symbols is not None:
        scan.successful_symbols = max(int(successful_symbols), 0)
    if failed_symbols is not None:
        scan.failed_symbols = max(int(failed_symbols), 0)

    if status == ScanStatus.FAILED.value:
        scan.status = ScanStatus.FAILED.value
        scan.error_message = error_message or scan.error_message or "Collector reported failure"
        scan.completed_at = utcnow()
        db.commit()
        db.refresh(scan)
        return scan

    if scan.csv_saved_at is None or not scan.candidates_processed:
        raise ConflictError("Scan cannot be completed before the CSV is archived and scanned")

    if scan.failed_symbols > 0 or status == ScanStatus.PARTIAL.value:
        scan.status = ScanStatus.PARTIAL.value
    else:
        scan.status = ScanStatus.COMPLETED.value
    if error_message:
        scan.error_message = error_message
    scan.completed_at = scan.completed_at or utcnow()
    db.commit()
    db.refresh(scan)
    return scan


def list_scans(
    db: Session,
    *,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ScanRun], int]:
    stmt = select(ScanRun)
    count_stmt = select(func.count(ScanRun.id))
    conditions = []
    if status:
        conditions.append(ScanRun.status == status)
    if date_from:
        conditions.append(ScanRun.started_at >= date_from)
    if date_to:
        conditions.append(ScanRun.started_at <= date_to)
    if search:
        like = f"%{search.strip()}%"
        conditions.append(ScanRun.csv_filename.ilike(like))
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    scans = db.scalars(
        stmt.order_by(ScanRun.started_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(scans), int(total)
