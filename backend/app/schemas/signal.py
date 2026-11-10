from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import ORMModel


class PublishSignalRequest(ORMModel):
    entry_price: Decimal = Field(gt=0)
    target_price: Decimal = Field(gt=0)
    stop_loss: Decimal | None = Field(default=None, gt=0)


class UpdateSignalRequest(ORMModel):
    entry_price: Decimal | None = Field(default=None, gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    stop_loss: Decimal | None = Field(default=None, gt=0)


class SignalActionRequest(ORMModel):
    reason: str | None = Field(default=None, max_length=1000)
    outcome: str | None = Field(default=None, max_length=24)


class PricePointOut(ORMModel):
    id: int
    ltp: Decimal
    captured_at: datetime
    event_type: str


class SignalOut(ORMModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    symbol: str
    direction: str
    scan_ltp: Decimal
    entry_price: Decimal
    target_price: Decimal
    stop_loss: Decimal | None
    current_ltp: Decimal | None
    price_updated_at: datetime | None
    published_at: datetime
    target_hit_at: datetime | None
    stoploss_hit_at: datetime | None
    closed_at: datetime | None
    status: str
    created_by: uuid.UUID | None
    updated_at: datetime
    pnl_percent: float | None = None
    target_progress_percent: float | None = None
    signal_move_percent: float | None = None
    target_reached: bool = False
    price_freshness: str = "UNKNOWN"


class SignalSummaryOut(ORMModel):
    total: int
    active: int
    target_hit: int
    stoploss_hit: int
    expired: int
    cancelled: int
    today_published: int = 0
    yesterday_published: int = 0
    target_hits_today: int = 0
    target_hits_yesterday: int = 0
    last_price_update: datetime | None = None


class SignalDetailOut(SignalOut):
    reason: str | None = None
    grade: str | None = None
    score: Decimal | None = None
    scan_timestamp: datetime | None = None
    price_history: list[PricePointOut] = Field(default_factory=list)
