from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict | None
    created_at: datetime


class SettingsOut(ORMModel):
    settings: dict


class SettingsUpdate(ORMModel):
    settings: dict[str, dict]


class DashboardOverview(ORMModel):
    today_scans: int
    total_scanned_stocks: int
    successful_scans: int
    failed_scans: int
    long_candidates: int
    short_candidates: int
    pending_approvals: int
    published_signals: int
    active_signals: int
    target_hits: int
    stoploss_hits: int
    csv_archive_count: int
    collector_status: str
    fyers_status: str
    market_data_provider: str = "FYERS"
    market_data_status: str = "NOT_CONFIGURED"
    stream_transport: str = "rest"


class PriceOut(ORMModel):
    symbol: str
    ltp: Decimal | None
    updated_at: datetime | None
    freshness: str
    signal_id: uuid.UUID | None = None
    direction: str | None = None
