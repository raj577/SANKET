"""Application settings with safe defaults, stored as JSON rows.

Scanner formula changes are versioned separately; these settings only control
enablement, grade floor and operational options.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AppSetting
from app.models.user import User
from app.scanner.scoring import DEFAULT_CONFIG

DEFAULT_SETTINGS: dict[str, dict] = {
    "scan_schedule": {
        "enabled": False,
        "times": ["09:20", "12:30", "15:20"],
        "timezone": "Asia/Kolkata",
    },
    "watchlist": {"symbols": []},
    "scanner": {
        "enabled": True,
        "long_enabled": True,
        "short_enabled": True,
        "min_grade": "C",
    },
    "csv_storage": {
        "retention_enabled": False,
        "retention_days": 3650,
    },
    "signal_policy": {
        "allow_publish_without_stop_loss": False,
    },
    "market_data": {
        "tracking_enabled": False,
        "persist_interval_seconds": 60,
        "stale_after_seconds": 300,
    },
}


def ensure_defaults(db: Session) -> None:
    """Persist any missing default settings rows (idempotent)."""
    changed = False
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=dict(value)))
            changed = True
    if changed:
        db.commit()


def get_all(db: Session) -> dict[str, dict]:
    rows = db.scalars(select(AppSetting)).all()
    merged = {key: dict(value) for key, value in DEFAULT_SETTINGS.items()}
    for row in rows:
        merged[row.key] = row.value
    return merged


def get_value(db: Session, key: str) -> dict:
    row = db.get(AppSetting, key)
    if row is not None:
        return row.value
    return dict(DEFAULT_SETTINGS.get(key, {}))


def update_values(
    db: Session, values: dict[str, dict], *, user: User | None = None
) -> dict[str, dict]:
    unknown = [key for key in values if key not in DEFAULT_SETTINGS]
    if unknown:
        from app.core.exceptions import ValidationError

        raise ValidationError(f"Unknown settings keys: {', '.join(sorted(unknown))}")

    for key, value in values.items():
        if not isinstance(value, dict):
            from app.core.exceptions import ValidationError

            raise ValidationError(f"Setting '{key}' must be a JSON object")
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value, updated_by=user.id if user else None)
            db.add(row)
        else:
            row.value = value
            if user is not None:
                row.updated_by = user.id
    return get_all(db)


def scanner_config_from_settings(db: Session):
    settings = get_settings()
    scanner = get_value(db, "scanner")
    return DEFAULT_CONFIG.with_overrides(
        long_enabled=bool(scanner.get("long_enabled", True)),
        short_enabled=bool(scanner.get("short_enabled", True)),
        min_grade=str(scanner.get("min_grade", settings.scanner_min_grade)),
    )
