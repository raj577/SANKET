"""Threshold detection and CSV archive storage unit tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from app.market_data.price_tracker import evaluate_threshold
from app.services.csv_storage import LocalStorageBackend


def test_long_thresholds():
    assert evaluate_threshold("LONG", Decimal("110"), Decimal("110"), Decimal("90")) == "TARGET_HIT"
    assert evaluate_threshold("LONG", Decimal("89"), Decimal("110"), Decimal("90")) == "STOPLOSS_HIT"
    assert evaluate_threshold("LONG", Decimal("100"), Decimal("110"), Decimal("90")) is None
    assert evaluate_threshold("LONG", Decimal("80"), None, None) is None


def test_short_thresholds():
    assert evaluate_threshold("SHORT", Decimal("90"), Decimal("90"), Decimal("110")) == "TARGET_HIT"
    assert evaluate_threshold("SHORT", Decimal("111"), Decimal("90"), Decimal("110")) == "STOPLOSS_HIT"
    assert evaluate_threshold("SHORT", Decimal("100"), Decimal("90"), Decimal("110")) is None
    assert evaluate_threshold("SHORT", Decimal("100"), None, Decimal("110")) is None


def test_sqlite_foreign_keys_are_enforced(client, db_session):
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_security_headers_are_present(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def test_local_storage_layout_and_checksum(tmp_path):
    backend = LocalStorageBackend(tmp_path)
    content = b"Symbol,Spot\nWIPRO,250.5\n"
    started = datetime(2026, 11, 9, 6, 50, 0, tzinfo=timezone.utc)  # 12:20 IST
    stored = backend.save_csv(content, started, uuid.uuid4())

    assert stored.relative_path.startswith("2026/11/09/")
    assert stored.filename.startswith("sensibull_oi_scan_122000")
    assert stored.size_bytes == len(content)
    assert len(stored.checksum_sha256) == 64
    assert backend.read_bytes(stored.relative_path) == content

    second = backend.save_csv(content, started, uuid.uuid4())
    assert second.filename != stored.filename
    assert backend.exists(stored.relative_path)
    assert backend.exists(second.relative_path)
