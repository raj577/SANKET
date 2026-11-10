"""Administrator API: scans, candidates, signals, users, settings and archives."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.exceptions import NotFoundError, ValidationError
from app.core.timeutils import to_ist, utcnow
from app.db.session import get_db
from app.models.audit import AdminAuditLog
from app.models.collector import CollectorToken
from app.models.enums import CandidateStatus, ScanStatus, SignalStatus
from app.models.scan import ScanCandidate, ScanRun
from app.models.signal import PublishedSignal
from app.models.user import User
from app.schemas.admin import (
    AuditLogOut,
    DashboardOverview,
    SettingsOut,
    SettingsUpdate,
)
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.schemas.common import Page
from app.schemas.scan import (
    ArchiveOut,
    CandidateDetailOut,
    CandidateOut,
    CandidateRejectRequest,
    ScanDetailOut,
    ScanOut,
)
from app.schemas.serializers import archive_out, scan_out, signal_detail_out, signal_out
from app.schemas.signal import (
    PricePointOut,
    PublishSignalRequest,
    SignalActionRequest,
    SignalDetailOut,
    SignalOut,
    UpdateSignalRequest,
)
from app.services import (
    audit_service,
    candidate_service,
    scan_service,
    settings_service,
    signal_service,
    user_service,
)
from app.services.csv_storage import get_storage
from app.services.ws_manager import broadcast_signal_event

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _page(items, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _today_utc_start() -> datetime:
    ist_now = to_ist(utcnow())
    start_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_ist.astimezone(timezone.utc)


# --------------------------------------------------------------------------- dashboard


@router.get("/overview", response_model=DashboardOverview)
def overview(db: Session = Depends(get_db)) -> DashboardOverview:
    start = _today_utc_start()

    today_scans = db.scalar(
        select(func.count(ScanRun.id)).where(ScanRun.started_at >= start)
    ) or 0
    successful = db.scalar(
        select(func.count(ScanRun.id)).where(
            ScanRun.started_at >= start, ScanRun.status == ScanStatus.COMPLETED.value
        )
    ) or 0
    failed = db.scalar(
        select(func.count(ScanRun.id)).where(
            ScanRun.started_at >= start, ScanRun.status == ScanStatus.FAILED.value
        )
    ) or 0
    scanned_stocks = db.scalar(
        select(func.coalesce(func.sum(ScanRun.successful_symbols), 0)).where(
            ScanRun.started_at >= start
        )
    ) or 0

    longs = db.scalar(
        select(func.count(ScanCandidate.id)).where(
            ScanCandidate.scanned_at >= start, ScanCandidate.direction == "LONG"
        )
    ) or 0
    shorts = db.scalar(
        select(func.count(ScanCandidate.id)).where(
            ScanCandidate.scanned_at >= start, ScanCandidate.direction == "SHORT"
        )
    ) or 0
    pending = db.scalar(
        select(func.count(ScanCandidate.id)).where(
            ScanCandidate.status == CandidateStatus.PENDING.value
        )
    ) or 0

    published = db.scalar(select(func.count(PublishedSignal.id))) or 0
    active = db.scalar(
        select(func.count(PublishedSignal.id)).where(
            PublishedSignal.status == SignalStatus.ACTIVE.value
        )
    ) or 0
    targets = db.scalar(
        select(func.count(PublishedSignal.id)).where(
            PublishedSignal.status == SignalStatus.TARGET_HIT.value
        )
    ) or 0
    stops = db.scalar(
        select(func.count(PublishedSignal.id)).where(
            PublishedSignal.status == SignalStatus.STOPLOSS_HIT.value
        )
    ) or 0
    archives = db.scalar(
        select(func.count(ScanRun.id)).where(ScanRun.csv_storage_path.is_not(None))
    ) or 0

    from app.core.config import get_settings
    from app.market_data.provider import provider_status

    settings = get_settings()
    provider, market_configured, stream_ready = provider_status()
    collector_configured = bool(settings.collector_bootstrap_token) or (
        db.scalar(
            select(func.count(CollectorToken.id)).where(CollectorToken.is_active.is_(True))
        )
        or 0
    ) > 0
    fyers_configured = provider == "fyers" and market_configured

    return DashboardOverview(
        today_scans=int(today_scans),
        total_scanned_stocks=int(scanned_stocks),
        successful_scans=int(successful),
        failed_scans=int(failed),
        long_candidates=int(longs),
        short_candidates=int(shorts),
        pending_approvals=int(pending),
        published_signals=int(published),
        active_signals=int(active),
        target_hits=int(targets),
        stoploss_hits=int(stops),
        csv_archive_count=int(archives),
        collector_status="CONFIGURED" if collector_configured else "NOT_CONFIGURED",
        fyers_status="CONFIGURED" if fyers_configured else "NOT_CONFIGURED",
        market_data_provider=provider.upper(),
        market_data_status="CONFIGURED" if market_configured else "NOT_CONFIGURED",
        stream_transport="websocket" if stream_ready else "rest",
    )


# ------------------------------------------------------------------------------- scans


@router.get("/scans", response_model=Page[ScanOut])
def list_scans(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    scans, total = scan_service.list_scans(
        db,
        status=status,
        date_from=date_from,
        date_to=date_to,
        search=search,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return _page([scan_out(scan) for scan in scans], total, page, page_size)


@router.get("/scans/{scan_id}", response_model=ScanDetailOut)
def get_scan(scan_id: uuid.UUID, db: Session = Depends(get_db)) -> ScanDetailOut:
    scan = scan_service.get_scan(db, scan_id)
    out = ScanDetailOut.model_validate(scan)
    out.warnings = [scan.error_message] if scan.error_message else []
    return out


# -------------------------------------------------------------------------- candidates


@router.get("/candidates", response_model=Page[CandidateOut])
def list_candidates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    scan_id: uuid.UUID | None = None,
    direction: str | None = None,
    status: str | None = None,
    grade: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    rows, total = candidate_service.list_candidates(
        db,
        scan_id=scan_id,
        direction=direction,
        status=status,
        grade=grade,
        symbol=symbol,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return _page([CandidateOut.model_validate(row) for row in rows], total, page, page_size)


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailOut)
def get_candidate(candidate_id: uuid.UUID, db: Session = Depends(get_db)) -> CandidateDetailOut:
    candidate = candidate_service.get_candidate(db, candidate_id)
    out = CandidateDetailOut.model_validate(candidate)
    signal = signal_service.get_signal_by_candidate(db, candidate.id)
    out.signal_id = signal.id if signal else None
    out.scan_status = candidate.scan.status if candidate.scan else None
    return out


@router.post("/candidates/{candidate_id}/approve", response_model=CandidateOut)
def approve_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> CandidateOut:
    candidate = candidate_service.approve(db, candidate_id, user)
    return CandidateOut.model_validate(candidate)


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateOut)
def reject_candidate(
    candidate_id: uuid.UUID,
    payload: CandidateRejectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> CandidateOut:
    candidate = candidate_service.reject(db, candidate_id, user, payload.reason)
    return CandidateOut.model_validate(candidate)


@router.post("/candidates/{candidate_id}/publish", response_model=SignalOut)
async def publish_candidate(
    candidate_id: uuid.UUID,
    payload: PublishSignalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignalOut:
    policy = settings_service.get_value(db, "signal_policy")
    signal = signal_service.publish_signal(
        db,
        candidate_id,
        entry_price=payload.entry_price,
        target_price=payload.target_price,
        stop_loss=payload.stop_loss,
        user=user,
        allow_missing_stop_loss=bool(policy.get("allow_publish_without_stop_loss", False)),
    )
    out = signal_out(signal)
    await broadcast_signal_event("signal_published", out.model_dump(mode="json"))
    return out


# ----------------------------------------------------------------------------- signals


@router.get("/signals", response_model=Page[SignalOut])
def list_signals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    direction: str | None = None,
    symbol: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    rows, total = signal_service.list_signals(
        db,
        status=status,
        direction=direction,
        symbol=symbol,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return _page([signal_out(row) for row in rows], total, page, page_size)


@router.get("/signals/{signal_id}", response_model=SignalDetailOut)
def get_signal(signal_id: uuid.UUID, db: Session = Depends(get_db)) -> SignalDetailOut:
    signal = signal_service.get_signal(db, signal_id)
    return signal_detail_out(signal, price_history=signal_service.history(db, signal_id))


@router.patch("/signals/{signal_id}", response_model=SignalOut)
async def update_signal(
    signal_id: uuid.UUID,
    payload: UpdateSignalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignalOut:
    policy = settings_service.get_value(db, "signal_policy")
    signal = signal_service.update_signal(
        db,
        signal_id,
        entry_price=payload.entry_price,
        target_price=payload.target_price,
        stop_loss=payload.stop_loss,
        user=user,
        allow_missing_stop_loss=bool(policy.get("allow_publish_without_stop_loss", False)),
    )
    out = signal_out(signal)
    await broadcast_signal_event("signal_updated", out.model_dump(mode="json"))
    return out


@router.post("/signals/{signal_id}/cancel", response_model=SignalOut)
async def cancel_signal(
    signal_id: uuid.UUID,
    payload: SignalActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignalOut:
    signal = signal_service.cancel_signal(db, signal_id, user, payload.reason)
    out = signal_out(signal)
    await broadcast_signal_event("signal_cancelled", out.model_dump(mode="json"))
    return out


@router.post("/signals/{signal_id}/close", response_model=SignalOut)
async def close_signal(
    signal_id: uuid.UUID,
    payload: SignalActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignalOut:
    allowed = {
        SignalStatus.EXPIRED.value,
        SignalStatus.TARGET_HIT.value,
        SignalStatus.STOPLOSS_HIT.value,
    }
    outcome = (payload.outcome or SignalStatus.EXPIRED.value).upper()
    if outcome not in allowed:
        raise ValidationError("Outcome must be EXPIRED, TARGET_HIT or STOPLOSS_HIT")
    signal = signal_service.close_signal(
        db, signal_id, user, outcome=outcome, reason=payload.reason
    )
    out = signal_out(signal)
    await broadcast_signal_event("signal_closed", out.model_dump(mode="json"))
    return out


@router.get("/signals/{signal_id}/history", response_model=list[PricePointOut])
def signal_history(
    signal_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[PricePointOut]:
    signal_service.get_signal(db, signal_id)
    return [PricePointOut.model_validate(row) for row in signal_service.history(db, signal_id, limit=limit)]


# ------------------------------------------------------------------------------- users


@router.get("/users", response_model=Page[UserOut])
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    users, total = user_service.list_users(db, (page - 1) * page_size, page_size)
    return _page([UserOut.model_validate(user) for user in users], total, page, page_size)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserOut:
    user = user_service.create_user(
        db, name=payload.name, email=payload.email, password=payload.password, role=payload.role
    )
    audit_service.record(
        db,
        action="USER_CREATED",
        entity_type="user",
        entity_id=str(user.id),
        details={"email": user.email, "role": user.role},
        user=admin,
    )
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserOut:
    user = user_service.update_user(
        db,
        user_id,
        name=payload.name,
        role=payload.role.value if payload.role else None,
        is_active=payload.is_active,
        password=payload.password,
    )
    audit_service.record(
        db,
        action="USER_UPDATED",
        entity_type="user",
        entity_id=str(user.id),
        details={"email": user.email, "role": user.role, "is_active": user.is_active},
        user=admin,
    )
    db.commit()
    return UserOut.model_validate(user)


# --------------------------------------------------------------------------- audit/settings


@router.get("/audit", response_model=Page[AuditLogOut])
def list_audit(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    action: str | None = None,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(AdminAuditLog)
    count_stmt = select(func.count(AdminAuditLog.id))
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
        count_stmt = count_stmt.where(AdminAuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AdminAuditLog.entity_type == entity_type)
        count_stmt = count_stmt.where(AdminAuditLog.entity_type == entity_type)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(AdminAuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return _page([AuditLogOut.model_validate(row) for row in rows], total, page, page_size)


@router.get("/settings", response_model=SettingsOut)
def get_settings_endpoint(db: Session = Depends(get_db)) -> SettingsOut:
    return SettingsOut(settings=settings_service.get_all(db))


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SettingsOut:
    values = settings_service.update_values(db, payload.settings, user=admin)
    audit_service.record(
        db,
        action="SETTINGS_UPDATED",
        entity_type="settings",
        details={"keys": sorted(payload.settings.keys())},
        user=admin,
    )
    db.commit()
    return SettingsOut(settings=values)


# ----------------------------------------------------------------------------- archives


@router.get("/archives", response_model=Page[ArchiveOut])
def list_archives(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(ScanRun).where(ScanRun.csv_storage_path.is_not(None))
    total = db.scalar(
        select(func.count(ScanRun.id)).where(ScanRun.csv_storage_path.is_not(None))
    ) or 0
    rows = db.scalars(
        stmt.order_by(ScanRun.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return _page([archive_out(row) for row in rows], total, page, page_size)


@router.get("/archives/{scan_id}/download")
def download_archive(scan_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    scan = scan_service.get_scan(db, scan_id)
    if not scan.csv_storage_path:
        raise NotFoundError("This scan has no archived CSV")
    content = get_storage().read_bytes(scan.csv_storage_path)
    filename = scan.csv_filename or f"scan-{scan.id}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Checksum-SHA256": scan.csv_checksum_sha256 or "",
        },
    )
