"""Timezone-aware helpers. All persisted timestamps are UTC; display uses IST."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ist_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """UTC half-open [start, end) window for one IST calendar day."""
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
