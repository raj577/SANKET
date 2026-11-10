"""Authenticated read-only signal endpoints for the user applications."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timeutils import ist_day_bounds_utc, to_ist, utcnow
from app.db.session import get_db
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.models.user import User
from app.schemas.common import Page
from app.schemas.serializers import signal_detail_out, signal_out
from app.schemas.signal import (
    PricePointOut,
    SignalDetailOut,
    SignalOut,
    SignalSummaryOut,
)
from app.services import signal_service

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=Page[SignalOut])
def list_signals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    direction: str | None = None,
    symbol: str | None = None,
    active_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows, total = signal_service.list_signals(
        db,
        status=status,
        direction=direction,
        symbol=symbol,
        active_only=active_only,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [signal_out(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/summary", response_model=SignalSummaryOut)
def signal_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SignalSummaryOut:
    rows = db.execute(
        select(PublishedSignal.status, func.count(PublishedSignal.id)).group_by(
            PublishedSignal.status
        )
    ).all()
    counts = {status: int(count) for status, count in rows}

    today = to_ist(utcnow()).date()
    t_start, t_end = ist_day_bounds_utc(today)
    y_start, _ = ist_day_bounds_utc(today - timedelta(days=1))

    def _count_in(column, start, end) -> int:
        return int(
            db.scalar(
                select(func.count(PublishedSignal.id)).where(
                    column.is_not(None),
                    column >= start,
                    column < end,
                )
            )
            or 0
        )

    today_published = int(
        db.scalar(
            select(func.count(PublishedSignal.id)).where(
                PublishedSignal.published_at >= t_start,
                PublishedSignal.published_at < t_end,
            )
        )
        or 0
    )
    yesterday_published = int(
        db.scalar(
            select(func.count(PublishedSignal.id)).where(
                PublishedSignal.published_at >= y_start,
                PublishedSignal.published_at < t_start,
            )
        )
        or 0
    )
    target_hits_today = _count_in(PublishedSignal.target_hit_at, t_start, t_end)
    target_hits_yesterday = _count_in(PublishedSignal.target_hit_at, y_start, t_start)

    last_update = db.scalar(
        select(func.max(PublishedSignal.price_updated_at)).where(
            PublishedSignal.status == SignalStatus.ACTIVE.value
        )
    )
    return SignalSummaryOut(
        total=sum(counts.values()),
        active=counts.get(SignalStatus.ACTIVE.value, 0),
        target_hit=counts.get(SignalStatus.TARGET_HIT.value, 0),
        stoploss_hit=counts.get(SignalStatus.STOPLOSS_HIT.value, 0),
        expired=counts.get(SignalStatus.EXPIRED.value, 0),
        cancelled=counts.get(SignalStatus.CANCELLED.value, 0),
        today_published=today_published,
        yesterday_published=yesterday_published,
        target_hits_today=target_hits_today,
        target_hits_yesterday=target_hits_yesterday,
        last_price_update=last_update,
    )


@router.get("/active", response_model=Page[SignalOut])
def active_signals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    direction: str | None = None,
    symbol: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows, total = signal_service.list_signals(
        db,
        active_only=True,
        direction=direction,
        symbol=symbol,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [signal_out(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{signal_id}", response_model=SignalDetailOut)
def get_signal(
    signal_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SignalDetailOut:
    signal = signal_service.get_signal(db, signal_id, visible_only=True)
    return signal_detail_out(signal, price_history=signal_service.history(db, signal_id))


@router.get("/{signal_id}/history", response_model=list[PricePointOut])
def signal_history(
    signal_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[PricePointOut]:
    signal_service.get_signal(db, signal_id, visible_only=True)
    return [
        PricePointOut.model_validate(row)
        for row in signal_service.history(db, signal_id, limit=limit)
    ]
