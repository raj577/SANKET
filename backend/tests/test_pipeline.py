"""End-to-end collector -> archive -> candidate -> signal -> tracking flow."""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.scan import ScanRun
from app.models.signal import PublishedSignal
from app.market_data.price_tracker import apply_price_tick

from .conftest import API, COLLECTOR_HEADERS


def _create_and_upload(client, sample_csv_bytes) -> str:
    scan_id = str(uuid.uuid4())
    created = client.post(
        f"{API}/collector/scans",
        headers=COLLECTOR_HEADERS,
        json={"scan_id": scan_id, "total_symbols": 213, "trigger": "test"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "PENDING"

    uploaded = client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("sensibull.csv", sample_csv_bytes, "text/csv")},
        data={"total_symbols": "213", "successful_symbols": "213", "failed_symbols": "0"},
    )
    assert uploaded.status_code == 200, uploaded.text
    return scan_id


def test_collector_pipeline_archives_csv_and_persists_candidates(
    client, sample_csv_bytes, db_session
):
    scan_id = _create_and_upload(client, sample_csv_bytes)
    body = client.get(
        f"{API}/collector/scans/{scan_id}", headers=COLLECTOR_HEADERS
    ).json()
    assert body["status"] == "COMPLETED"
    assert body["long_candidates_count"] == 8
    assert body["short_candidates_count"] == 7
    assert body["csv_checksum_sha256"]
    assert body["csv_storage_path"]

    scan = db_session.get(ScanRun, uuid.UUID(scan_id))
    assert scan is not None
    assert scan.candidates_processed is True
    assert scan.csv_filename and scan.csv_filename.endswith(".csv")

    from app.services.csv_storage import get_storage

    stored_path = get_storage().local_path(scan.csv_storage_path)
    assert stored_path is not None and stored_path.is_file()
    assert stored_path.read_bytes() == sample_csv_bytes

    # Re-uploading the same bytes is idempotent.
    again = client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("sensibull.csv", sample_csv_bytes, "text/csv")},
    )
    assert again.status_code == 200
    assert again.json()["long_candidates_count"] == 8

    # A different payload for an already-archived scan is refused.
    conflict = client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("other.csv", sample_csv_bytes + b"\n", "text/csv")},
    )
    assert conflict.status_code == 409

    completed = client.post(
        f"{API}/collector/scans/{scan_id}/complete",
        headers=COLLECTOR_HEADERS,
        json={"status": "COMPLETED", "successful_symbols": 213, "failed_symbols": 0},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"


def test_approve_publish_and_target_tracking(client, admin_headers, sample_csv_bytes, db_session):
    scan_id = _create_and_upload(client, sample_csv_bytes)

    candidates = client.get(
        f"{API}/admin/candidates",
        headers=admin_headers,
        params={"scan_id": scan_id, "direction": "LONG", "page_size": 50},
    )
    assert candidates.status_code == 200
    rows = candidates.json()["items"]
    assert len(rows) == 8
    candidate = rows[0]
    assert candidate["status"] == "PENDING"

    approved = client.post(
        f"{API}/admin/candidates/{candidate['id']}/approve", headers=admin_headers
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    entry = Decimal(str(candidate["scan_ltp"]))
    target = entry * Decimal("1.10")
    stop = entry * Decimal("0.95")
    published = client.post(
        f"{API}/admin/candidates/{candidate['id']}/publish",
        headers=admin_headers,
        json={
            "entry_price": str(entry),
            "target_price": str(target),
            "stop_loss": str(stop),
        },
    )
    assert published.status_code == 200, published.text
    signal = published.json()
    assert signal["status"] == "ACTIVE"
    assert signal["symbol"] == candidate["symbol"]
    # No live quote has been observed, so no price may be presented as current.
    assert signal["current_ltp"] is None
    assert signal["price_freshness"] == "UNKNOWN"

    # A LONG signal cannot target below entry.
    another = rows[1]
    client.post(f"{API}/admin/candidates/{another['id']}/approve", headers=admin_headers)
    invalid = client.post(
        f"{API}/admin/candidates/{another['id']}/publish",
        headers=admin_headers,
        json={
            "entry_price": str(entry),
            "target_price": str(entry * Decimal("0.9")),
            "stop_loss": str(stop),
        },
    )
    assert invalid.status_code == 422

    # Target crossing is detected once and persisted with its observation time.
    db_signal = db_session.get(PublishedSignal, uuid.UUID(signal["id"]))
    first = apply_price_tick(db_session, db_signal, target)
    assert first["event"] == "TARGET_HIT"
    second = apply_price_tick(db_session, db_signal, target + Decimal("1"))
    assert second["event"] is None
    assert second["status"] == "TARGET_HIT"

    detail = client.get(f"{API}/admin/signals/{signal['id']}", headers=admin_headers)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == "TARGET_HIT"
    assert Decimal(detail_body["current_ltp"]) == target
    assert any(point["event_type"] == "TARGET_HIT" for point in detail_body["price_history"])

    history = client.get(
        f"{API}/signals/{signal['id']}/history", headers=admin_headers
    )
    assert history.status_code == 200
    assert len(history.json()) >= 2

    summary = client.get(f"{API}/signals/summary", headers=admin_headers)
    assert summary.status_code == 200
    assert summary.json()["total"] == 1
    assert summary.json()["target_hit"] == 1
    assert summary.json()["active"] == 0


def test_repeated_symbols_across_dates_are_deduplicated(client, sample_csv_bytes):
    lines = sample_csv_bytes.decode("utf-8").splitlines()
    combined = "\n".join([lines[0], *lines[1:], *lines[1:]]).encode("utf-8")

    scan_id = str(uuid.uuid4())
    client.post(
        f"{API}/collector/scans",
        headers=COLLECTOR_HEADERS,
        json={"scan_id": scan_id, "total_symbols": 213},
    )
    uploaded = client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("multi.csv", combined, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["status"] == "COMPLETED"
    assert body["long_candidates_count"] == 8
    assert body["short_candidates_count"] == 7


def test_disabled_scanner_archives_without_candidates(client, db_session, sample_csv_bytes):
    from app.services import settings_service

    settings_service.update_values(db_session, {"scanner": {"enabled": False}})
    db_session.commit()

    scan_id = _create_and_upload(client, sample_csv_bytes)
    body = client.get(
        f"{API}/collector/scans/{scan_id}", headers=COLLECTOR_HEADERS
    ).json()
    assert body["status"] == "PARTIAL"
    assert body["long_candidates_count"] == 0
    assert body["short_candidates_count"] == 0
    assert body["csv_storage_path"]
    assert "Scanner disabled" in (body["error_message"] or "")


def test_archive_download_returns_exact_bytes(client, admin_headers, sample_csv_bytes):
    scan_id = _create_and_upload(client, sample_csv_bytes)
    listing = client.get(f"{API}/admin/archives", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["scan_id"] == scan_id

    download = client.get(
        f"{API}/admin/archives/{scan_id}/download", headers=admin_headers
    )
    assert download.status_code == 200
    assert download.content == sample_csv_bytes
    assert download.headers["x-checksum-sha256"] == item["csv_checksum_sha256"]
