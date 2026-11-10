"""Date-wise filtering, summary day counts and signal-move percentage."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.timeutils import to_ist, utcnow
from app.market_data.price_tracker import apply_price_tick
from app.models.signal import PublishedSignal

from .conftest import API
from .test_pipeline import _create_and_upload

IST = ZoneInfo("Asia/Kolkata")


def _publish_long(client, admin_headers, scan_id: str, index: int) -> dict:
    rows = client.get(
        f"{API}/admin/candidates",
        headers=admin_headers,
        params={"scan_id": scan_id, "direction": "LONG", "page_size": 50},
    ).json()["items"]
    candidate = rows[index]
    client.post(f"{API}/admin/candidates/{candidate['id']}/approve", headers=admin_headers)
    entry = Decimal(str(candidate["scan_ltp"]))
    published = client.post(
        f"{API}/admin/candidates/{candidate['id']}/publish",
        headers=admin_headers,
        json={
            "entry_price": str(entry),
            "target_price": str(entry * Decimal("1.10")),
            "stop_loss": str(entry * Decimal("0.95")),
        },
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_date_filters_summary_and_move_percent(client, admin_headers, sample_csv_bytes, db_session):
    scan_id = _create_and_upload(client, sample_csv_bytes)
    today_signal = _publish_long(client, admin_headers, scan_id, index=0)
    yesterday_signal = _publish_long(client, admin_headers, scan_id, index=1)

    # Backdate one signal to yesterday, noon IST.
    now_ist = to_ist(utcnow())
    yesterday_noon_ist = (
        now_ist - timedelta(days=1)
    ).replace(hour=12, minute=0, second=0, microsecond=0)
    stored = db_session.get(PublishedSignal, uuid.UUID(yesterday_signal["id"]))
    stored.published_at = yesterday_noon_ist
    db_session.commit()

    today = now_ist.date().isoformat()
    yesterday = (now_ist.date() - timedelta(days=1)).isoformat()

    todays = client.get(
        f"{API}/signals", headers=admin_headers, params={"date_from": today}
    ).json()
    assert todays["total"] == 1
    assert todays["items"][0]["id"] == today_signal["id"]

    yesterdays = client.get(
        f"{API}/signals",
        headers=admin_headers,
        params={"date_from": yesterday, "date_to": yesterday},
    ).json()
    assert yesterdays["total"] == 1
    assert yesterdays["items"][0]["id"] == yesterday_signal["id"]

    admin_view = client.get(
        f"{API}/admin/signals",
        headers=admin_headers,
        params={"date_from": today},
    ).json()
    assert admin_view["total"] == 1

    summary = client.get(f"{API}/signals/summary", headers=admin_headers).json()
    assert summary["today_published"] == 1
    assert summary["yesterday_published"] == 1
    assert summary["target_hits_today"] == 0

    # Target hit today -> counted on the today window, and the move from the
    # signal-time LTP to the latest LTP is exactly +10% (target = entry * 1.10
    # with entry equal to the scan LTP).
    signal = db_session.get(PublishedSignal, uuid.UUID(today_signal["id"]))
    tick = apply_price_tick(db_session, signal, Decimal(str(today_signal["target_price"])))
    assert tick["event"] == "TARGET_HIT"

    summary = client.get(f"{API}/signals/summary", headers=admin_headers).json()
    assert summary["target_hits_today"] == 1

    detail = client.get(
        f"{API}/signals/{today_signal['id']}", headers=admin_headers
    ).json()
    assert detail["status"] == "TARGET_HIT"
    assert detail["signal_move_percent"] is not None
    assert abs(detail["signal_move_percent"] - 10.0) < 0.001

    # SHORT move is direction-aware: falling price is positive movement.
    scan_id2 = _create_and_upload(client, sample_csv_bytes)
    short_rows = client.get(
        f"{API}/admin/candidates",
        headers=admin_headers,
        params={"scan_id": scan_id2, "direction": "SHORT", "page_size": 5},
    ).json()["items"]
    short = short_rows[0]
    client.post(f"{API}/admin/candidates/{short['id']}/approve", headers=admin_headers)
    entry = Decimal(str(short["scan_ltp"]))
    short_signal = client.post(
        f"{API}/admin/candidates/{short['id']}/publish",
        headers=admin_headers,
        json={
            "entry_price": str(entry),
            "target_price": str(entry * Decimal("0.90")),
            "stop_loss": str(entry * Decimal("1.05")),
        },
    ).json()
    stored_short = db_session.get(PublishedSignal, uuid.UUID(short_signal["id"]))
    apply_price_tick(db_session, stored_short, entry * Decimal("0.90"))
    moved = client.get(f"{API}/signals/{short_signal['id']}", headers=admin_headers).json()
    assert moved["signal_move_percent"] is not None
    assert abs(moved["signal_move_percent"] - 10.0) < 0.001
    assert abs(moved["pnl_percent"] - 10.0) < 0.001  # entry == scan LTP here

    # No live quote observed -> no fabricated movement.
    fresh = client.get(
        f"{API}/signals/{yesterday_signal['id']}", headers=admin_headers
    ).json()
    assert fresh["current_ltp"] is None
    assert fresh["signal_move_percent"] is None
