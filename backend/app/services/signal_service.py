"""Signal publication, editing and lifecycle."""
from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import ensure_aware, ist_day_bounds_utc, utcnow
from app.models.enums import (
    AuditAction,
    CandidateStatus,
    Direction,
    PriceEventType,
    SignalStatus,
)
from app.models.scan import ScanCandidate
from app.models.signal import PublishedSignal, SignalPriceHistory
from app.models.user import User
from app.services import audit_service, notification_service

ACTIVE_STATUSES = {SignalStatus.ACTIVE.value}
VISIBLE_STATUSES = {
    SignalStatus.ACTIVE.value,
    SignalStatus.TARGET_HIT.value,
    SignalStatus.STOPLOSS_HIT.value,
    SignalStatus.EXPIRED.value,
    SignalStatus.CANCELLED.value,
}


def _validate_prices(
    direction: str,
    entry: Decimal,
    target: Decimal,
    stop_loss: Decimal | None,
    *,
    allow_missing_stop_loss: bool,
) -> None:
    if entry <= 0:
        raise ValidationError("Entry price must be greater than zero")
    if target <= 0:
        raise ValidationError("Target price must be greater than zero")

    if direction == Direction.LONG.value:
        if target <= entry:
            raise ValidationError("For a LONG signal the target must be above the entry")
        if stop_loss is None:
            if not allow_missing_stop_loss:
                raise ValidationError("A stop-loss is required for LONG signals")
        elif stop_loss >= entry:
            raise ValidationError("For a LONG signal the stop-loss must be below the entry")
    elif direction == Direction.SHORT.value:
        if target >= entry:
            raise ValidationError("For a SHORT signal the target must be below the entry")
        if stop_loss is None:
            if not allow_missing_stop_loss:
                raise ValidationError("A stop-loss is required for SHORT signals")
        elif stop_loss <= entry:
            raise ValidationError("For a SHORT signal the stop-loss must be above the entry")
    else:
        raise ValidationError("Direction must be LONG or SHORT")


def get_signal(db: Session, signal_id: uuid.UUID, *, visible_only: bool = False) -> PublishedSignal:
    signal = db.get(PublishedSignal, signal_id)
    if signal is None or (visible_only and signal.status not in VISIBLE_STATUSES):
        raise NotFoundError("Signal not found")
    return signal


def get_signal_by_candidate(db: Session, candidate_id: uuid.UUID) -> PublishedSignal | None:
    return db.scalar(select(PublishedSignal).where(PublishedSignal.candidate_id == candidate_id))


def _add_history(
    db: Session, signal: PublishedSignal, ltp: Decimal, event: str, captured_at
) -> None:
    """Append an observed price point.

    Only real observations are stored: the scan LTP at publication time, live
    LTPs from the tracker, and the last observed LTP at close. The admin entry
    price is never labelled as a market observation.
    """
    db.add(
        SignalPriceHistory(
            signal_id=signal.id,
            ltp=ltp,
            captured_at=captured_at,
            event_type=event,
        )
    )


def publish_signal(
    db: Session,
    candidate_id: uuid.UUID,
    *,
    entry_price: Decimal,
    target_price: Decimal,
    stop_loss: Decimal | None,
    user: User,
    allow_missing_stop_loss: bool = False,
) -> PublishedSignal:
    candidate = db.get(ScanCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found")
    if candidate.status != CandidateStatus.APPROVED.value:
        raise ConflictError("Candidate must be approved before it can be published")
    if get_signal_by_candidate(db, candidate_id) is not None:
        raise ConflictError("A signal already exists for this candidate")

    _validate_prices(
        candidate.direction,
        entry_price,
        target_price,
        stop_loss,
        allow_missing_stop_loss=allow_missing_stop_loss,
    )

    now = utcnow()
    signal = PublishedSignal(
        candidate_id=candidate.id,
        symbol=candidate.symbol,
        direction=candidate.direction,
        scan_ltp=candidate.scan_ltp,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        # No live quote has been observed yet. Keeping this empty is what makes
        # the price freshness honestly report UNKNOWN until the tracker runs.
        current_ltp=None,
        price_updated_at=None,
        published_at=now,
        status=SignalStatus.ACTIVE.value,
        created_by=user.id,
    )
    db.add(signal)
    db.flush()
    _add_history(
        db,
        signal,
        candidate.scan_ltp,
        PriceEventType.PUBLISHED.value,
        ensure_aware(candidate.scanned_at),
    )

    candidate.status = CandidateStatus.PUBLISHED.value
    audit_service.record(
        db,
        action=AuditAction.SIGNAL_PUBLISHED.value,
        entity_type="published_signal",
        entity_id=str(signal.id),
        details={
            "candidate_id": str(candidate.id),
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_price": str(entry_price),
            "target_price": str(target_price),
            "stop_loss": str(stop_loss) if stop_loss is not None else None,
        },
        user=user,
    )
    db.commit()
    db.refresh(signal)
    notification_service.notify_signal_published(signal.id, signal.symbol)
    return signal


def update_signal(
    db: Session,
    signal_id: uuid.UUID,
    *,
    entry_price: Decimal | None = None,
    target_price: Decimal | None = None,
    stop_loss: Decimal | None = None,
    user: User,
    allow_missing_stop_loss: bool = False,
) -> PublishedSignal:
    signal = get_signal(db, signal_id)
    if signal.status != SignalStatus.ACTIVE.value:
        raise ConflictError("Only active signals can be modified")

    new_entry = entry_price if entry_price is not None else signal.entry_price
    new_target = target_price if target_price is not None else signal.target_price
    new_stop = stop_loss if stop_loss is not None else signal.stop_loss
    _validate_prices(
        signal.direction,
        new_entry,
        new_target,
        new_stop,
        allow_missing_stop_loss=allow_missing_stop_loss,
    )

    changes: dict[str, dict[str, str | None]] = {}
    if entry_price is not None and entry_price != signal.entry_price:
        changes["entry_price"] = {"from": str(signal.entry_price), "to": str(entry_price)}
        signal.entry_price = entry_price
        audit_action = AuditAction.SIGNAL_ENTRY_CHANGED.value
        audit_service.record(
            db, action=audit_action, entity_type="published_signal", entity_id=str(signal.id),
            details={"field": "entry_price", **changes["entry_price"], "symbol": signal.symbol}, user=user,
        )
    if target_price is not None and target_price != signal.target_price:
        changes["target_price"] = {"from": str(signal.target_price), "to": str(target_price)}
        signal.target_price = target_price
        audit_service.record(
            db, action=AuditAction.SIGNAL_TARGET_CHANGED.value, entity_type="published_signal",
            entity_id=str(signal.id),
            details={"field": "target_price", **changes["target_price"], "symbol": signal.symbol}, user=user,
        )
    if stop_loss is not None and stop_loss != signal.stop_loss:
        changes["stop_loss"] = {
            "from": str(signal.stop_loss) if signal.stop_loss is not None else None,
            "to": str(stop_loss),
        }
        signal.stop_loss = stop_loss
        audit_service.record(
            db, action=AuditAction.SIGNAL_STOPLOSS_CHANGED.value, entity_type="published_signal",
            entity_id=str(signal.id),
            details={"field": "stop_loss", **changes["stop_loss"], "symbol": signal.symbol}, user=user,
        )

    db.commit()
    db.refresh(signal)
    return signal


def cancel_signal(db: Session, signal_id: uuid.UUID, user: User, reason: str | None = None) -> PublishedSignal:
    signal = get_signal(db, signal_id)
    if signal.status != SignalStatus.ACTIVE.value:
        raise ConflictError("Only active signals can be cancelled")
    now = utcnow()
    signal.status = SignalStatus.CANCELLED.value
    signal.closed_at = now
    if signal.current_ltp is not None:
        _add_history(
            db, signal, signal.current_ltp, PriceEventType.CANCELLED.value, now
        )
    audit_service.record(
        db,
        action=AuditAction.SIGNAL_CANCELLED.value,
        entity_type="published_signal",
        entity_id=str(signal.id),
        details={"symbol": signal.symbol, "reason": reason},
        user=user,
    )
    db.commit()
    db.refresh(signal)
    notification_service.notify_signal_event(signal.id, SignalStatus.CANCELLED.value, signal.symbol)
    return signal


def close_signal(
    db: Session, signal_id: uuid.UUID, user: User, *, outcome: str = SignalStatus.EXPIRED.value,
    reason: str | None = None,
) -> PublishedSignal:
    signal = get_signal(db, signal_id)
    if signal.status == SignalStatus.CANCELLED.value:
        raise ConflictError("Signal is already cancelled")
    now = utcnow()
    signal.status = outcome if outcome in {
        SignalStatus.EXPIRED.value, SignalStatus.TARGET_HIT.value, SignalStatus.STOPLOSS_HIT.value
    } else SignalStatus.EXPIRED.value
    signal.closed_at = now
    if signal.current_ltp is not None:
        _add_history(db, signal, signal.current_ltp, PriceEventType.CLOSED.value, now)
    audit_service.record(
        db,
        action=AuditAction.SIGNAL_CLOSED.value,
        entity_type="published_signal",
        entity_id=str(signal.id),
        details={"symbol": signal.symbol, "outcome": signal.status, "reason": reason},
        user=user,
    )
    db.commit()
    db.refresh(signal)
    notification_service.notify_signal_event(signal.id, signal.status, signal.symbol)
    return signal


def list_signals(
    db: Session,
    *,
    status: str | None = None,
    direction: str | None = None,
    symbol: str | None = None,
    active_only: bool = False,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[PublishedSignal], int]:
    stmt = select(PublishedSignal)
    count_stmt = select(func.count(PublishedSignal.id))
    conditions = []
    if active_only:
        conditions.append(PublishedSignal.status == SignalStatus.ACTIVE.value)
    elif status:
        conditions.append(PublishedSignal.status == status.upper())
    if direction:
        conditions.append(PublishedSignal.direction == direction.upper())
    if symbol:
        conditions.append(PublishedSignal.symbol.ilike(f"%{symbol.strip().upper()}%"))
    if date_from is not None:
        start, _ = ist_day_bounds_utc(date_from)
        conditions.append(PublishedSignal.published_at >= start)
    if date_to is not None:
        _, end = ist_day_bounds_utc(date_to)
        conditions.append(PublishedSignal.published_at < end)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(PublishedSignal.published_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), int(total)


def history(db: Session, signal_id: uuid.UUID, *, limit: int = 500) -> list[SignalPriceHistory]:
    return list(
        db.scalars(
            select(SignalPriceHistory)
            .where(SignalPriceHistory.signal_id == signal_id)
            .order_by(SignalPriceHistory.captured_at.asc())
            .limit(limit)
        ).all()
    )
