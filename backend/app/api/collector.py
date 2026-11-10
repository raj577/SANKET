"""Collector endpoints used by the Chrome extension service worker."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CollectorContext, require_collector
from app.core.exceptions import ValidationError
from app.core.timeutils import utcnow
from app.db.session import get_db
from app.models.collector import CollectorToken
from app.models.enums import ScanStatus
from app.models.scan import ScanRun
from app.schemas.scan import (
    CollectorStatusOut,
    ScanCompleteRequest,
    ScanCreateRequest,
    ScanOut,
    ScanProgressRequest,
)
from app.scanner.scoring import DEFAULT_CONFIG
from app.services import scan_service
from app.schemas.serializers import scan_out

router = APIRouter(prefix="/collector", tags=["collector"])


@router.post("/scans", response_model=ScanOut)
def create_scan(
    payload: ScanCreateRequest,
    db: Session = Depends(get_db),
    collector: CollectorContext = Depends(require_collector),
) -> ScanOut:
    scan = scan_service.create_scan(
        db,
        scan_id=payload.scan_id,
        started_at=payload.started_at,
        total_symbols=payload.total_symbols,
        trigger=payload.trigger or collector.name,
    )
    return scan_out(scan)


@router.post("/scans/{scan_id}/progress", response_model=ScanOut)
def record_progress(
    scan_id: uuid.UUID,
    payload: ScanProgressRequest,
    db: Session = Depends(get_db),
    _: CollectorContext = Depends(require_collector),
) -> ScanOut:
    scan = scan_service.get_scan(db, scan_id)
    scan = scan_service.record_progress(
        db,
        scan,
        current_symbol=payload.current_symbol,
        total_symbols=payload.total_symbols,
        successful_symbols=payload.successful_symbols,
        failed_symbols=payload.failed_symbols,
    )
    return scan_out(scan)


@router.post("/scans/{scan_id}/csv", response_model=ScanOut)
async def upload_csv(
    scan_id: uuid.UUID,
    file: UploadFile = File(...),
    total_symbols: int | None = Form(default=None),
    successful_symbols: int | None = Form(default=None),
    failed_symbols: int | None = Form(default=None),
    db: Session = Depends(get_db),
    _: CollectorContext = Depends(require_collector),
) -> ScanOut:
    settings = get_settings()
    scan = scan_service.get_scan(db, scan_id)
    content = await file.read(settings.storage_max_csv_bytes + 1)
    if len(content) > settings.storage_max_csv_bytes:
        raise ValidationError(
            f"CSV exceeds the {settings.storage_max_csv_bytes} byte upload limit",
            status_code=413,
            code="payload_too_large",
        )
    scan = scan_service.handle_csv_upload(
        db,
        scan,
        content=content,
        total_symbols=total_symbols,
        successful_symbols=successful_symbols,
        failed_symbols=failed_symbols,
    )
    return scan_out(scan)


@router.post("/scans/{scan_id}/complete", response_model=ScanOut)
def complete_scan(
    scan_id: uuid.UUID,
    payload: ScanCompleteRequest,
    db: Session = Depends(get_db),
    _: CollectorContext = Depends(require_collector),
) -> ScanOut:
    scan = scan_service.get_scan(db, scan_id)
    scan = scan_service.complete_scan(
        db,
        scan,
        status=payload.status,
        successful_symbols=payload.successful_symbols,
        failed_symbols=payload.failed_symbols,
        error_message=payload.error_message,
    )
    return scan_out(scan)


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(
    scan_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CollectorContext = Depends(require_collector),
) -> ScanOut:
    return scan_out(scan_service.get_scan(db, scan_id))


@router.get("/status", response_model=CollectorStatusOut)
def collector_status(
    db: Session = Depends(get_db),
    _: CollectorContext = Depends(require_collector),
) -> CollectorStatusOut:
    settings = get_settings()
    active = db.scalar(
        select(func.count(ScanRun.id)).where(
            ScanRun.status.in_([ScanStatus.PENDING.value, ScanStatus.RUNNING.value])
        )
    ) or 0
    last = db.scalar(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(1))
    has_tokens = bool(settings.collector_bootstrap_token) or (
        db.scalar(select(func.count(CollectorToken.id)).where(CollectorToken.is_active.is_(True))) or 0
    ) > 0
    return CollectorStatusOut(
        server_time=utcnow(),
        active_scans=int(active),
        last_scan=scan_out(last) if last else None,
        collector_authenticated=has_tokens,
        storage_backend=settings.storage_backend,
        scanner_version=DEFAULT_CONFIG.versioned_id(),
    )
