"""Notification hooks.

Push (FCM) and live broadcast are integrated in later phases. These hooks are
intentionally side-effect free in the foundation so the data pipeline never
depends on an external provider.
"""
from __future__ import annotations

import uuid

from app.core.logging import get_logger

logger = get_logger(__name__)


def notify_scan_failed(scan_id: uuid.UUID, message: str | None) -> None:
    logger.warning("scan_failed", extra={"scan_id": str(scan_id), "error": message})


def notify_signal_published(signal_id: uuid.UUID, symbol: str) -> None:
    logger.info("signal_published", extra={"signal_id": str(signal_id), "symbol": symbol})


def notify_signal_event(signal_id: uuid.UUID, event: str, symbol: str) -> None:
    logger.info("signal_event", extra={"signal_id": str(signal_id), "event": event, "symbol": symbol})
