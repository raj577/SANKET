"""Regression guards: adding the pattern scanner must not change the OI scanner.

These assertions lock the OI contract (CSV thresholds, candidate counts, API
filters and dashboard counts) to the behaviour that existed before the pattern
scanner was introduced.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import ScanType
from app.models.scan import PatternCandidate, ScanCandidate, ScanRun
from app.scanner.engine import scan_csv
from app.scanner.scoring import DEFAULT_CONFIG
from app.services import pattern_scan_service

from .conftest import API, COLLECTOR_HEADERS, SAMPLE_CSV
from .pattern_fixtures import ist, make_frame, make_instrument


def test_oi_scanner_output_is_unchanged():
    result = scan_csv(SAMPLE_CSV)
    assert result.rows_read == 213
    assert len(result.longs) == 8
    assert len(result.shorts) == 7
    assert result.warnings == []

    wipro = next(c for c in result.longs if c.symbol == "WIPRO")
    assert wipro.score >= 400
    assert wipro.confirmation_count >= DEFAULT_CONFIG.confirmation_minimum
    assert "ATM Put Writing" in wipro.reason


def _upload_oi_scan(client, sample_csv_bytes) -> str:
    scan_id = str(uuid.uuid4())
    created = client.post(
        f"{API}/collector/scans",
        headers=COLLECTOR_HEADERS,
        json={"scan_id": scan_id, "total_symbols": 213},
    )
    assert created.status_code == 200, created.text
    uploaded = client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("sensibull.csv", sample_csv_bytes, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    return scan_id


def test_oi_pipeline_still_persists_candidates_and_publishes(
    client, admin_headers, sample_csv_bytes, db_session
):
    scan_id = _upload_oi_scan(client, sample_csv_bytes)
    body = client.get(f"{API}/collector/scans/{scan_id}", headers=COLLECTOR_HEADERS).json()
    assert body["long_candidates_count"] == 8
    assert body["short_candidates_count"] == 7
    assert body["status"] == "COMPLETED"

    scan = db_session.get(ScanRun, uuid.UUID(scan_id))
    assert scan.scan_type == ScanType.OI.value
    assert scan.timeframe is None
    # The OI candidate table still owns every OI candidate.
    oi_candidates = db_session.query(ScanCandidate).filter_by(scan_id=scan.id).count()
    assert oi_candidates == 15
    assert db_session.query(PatternCandidate).count() == 0

    rows = client.get(
        f"{API}/admin/candidates",
        headers=admin_headers,
        params={"scan_id": scan_id, "direction": "LONG"},
    ).json()["items"]
    first = rows[0]
    approved = client.post(
        f"{API}/admin/candidates/{first['id']}/approve", headers=admin_headers
    )
    assert approved.status_code == 200
    entry = Decimal(str(first["scan_ltp"]))
    published = client.post(
        f"{API}/admin/candidates/{first['id']}/publish",
        headers=admin_headers,
        json={
            "entry_price": str(entry),
            "target_price": str(entry * Decimal("1.08")),
            "stop_loss": str(entry * Decimal("0.96")),
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "ACTIVE"


def test_oi_scan_list_does_not_leak_pattern_runs(
    client, admin_headers, sample_csv_bytes, db_session
):
    _upload_oi_scan(client, sample_csv_bytes)

    pattern_scan = pattern_scan_service.create_scan(
        db_session, total_symbols=2, timeframe="60"
    )
    pattern_scan.status = "COMPLETED"
    pattern_scan.successful_symbols = 2
    db_session.commit()

    listing = client.get(f"{API}/admin/scans", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["scan_type"] == ScanType.OI.value

    filtered = client.get(
        f"{API}/admin/scans",
        headers=admin_headers,
        params={"scan_type": ScanType.AVWAP_PATTERN.value},
    )
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == str(pattern_scan.id)


def test_oi_candidate_list_excludes_pattern_candidates(
    client, admin_headers, sample_csv_bytes, db_session
):
    _upload_oi_scan(client, sample_csv_bytes)
    pattern_scan = pattern_scan_service.create_scan(
        db_session, total_symbols=1, timeframe="60"
    )
    db_session.add(
        PatternCandidate(
            scan_id=pattern_scan.id,
            symbol="NSE:NIFTY26NOVFUT",
            underlying="NIFTY",
            timeframe="60",
            pattern_type="AVWAP TOUCH",
            candle_count=1,
            last_price=Decimal("100.1"),
            avwap=Decimal("100.0"),
            distance_pct=Decimal("0.1"),
            avg_body_ratio=Decimal("0.2"),
            max_body_ratio=Decimal("0.25"),
            window_range_pct=Decimal("0.004"),
            touched=True,
            status="PENDING",
            reason="AVWAP TOUCH · 1 candle(s)",
        )
    )
    db_session.commit()

    oi_listing = client.get(f"{API}/admin/candidates", headers=admin_headers)
    assert oi_listing.status_code == 200
    assert oi_listing.json()["total"] == 15

    pattern_listing = client.get(f"{API}/admin/pattern-candidates", headers=admin_headers)
    assert pattern_listing.status_code == 200
    assert pattern_listing.json()["total"] == 1


def test_dashboard_counts_ignore_pattern_runs(client, admin_headers, db_session):
    db_session.add(
        ScanRun(
            started_at=datetime.now(timezone.utc),
            status="COMPLETED",
            scan_type=ScanType.OI.value,
            total_symbols=10,
            successful_symbols=10,
            failed_symbols=0,
            candidates_processed=True,
        )
    )
    pattern_scan = pattern_scan_service.create_scan(
        db_session, total_symbols=7, timeframe="60"
    )
    pattern_scan.status = "COMPLETED"
    pattern_scan.successful_symbols = 7
    db_session.commit()

    overview = client.get(f"{API}/admin/overview", headers=admin_headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["today_scans"] == 1
    assert body["successful_scans"] == 1
    assert body["total_scanned_stocks"] == 10
    assert body["failed_scans"] == 0


def test_pattern_run_does_not_create_oi_candidates(db_session):
    instrument = make_instrument("NSE:NIFTY26NOVFUT", "NIFTY")
    scan = pattern_scan_service.create_scan(db_session, total_symbols=1, timeframe="60")
    from .pattern_fixtures import FakeHistoryService

    pattern_scan_service.run_scan_job(
        scan.id,
        None,
        "60",
        True,
        True,
        history_service=FakeHistoryService(make_frame(pattern_count=1)),
        instruments=[instrument],
        now=ist(2026, 11, 4, 16, 0),
    )
    db_session.expire_all()

    assert db_session.query(ScanCandidate).count() == 0
    assert db_session.query(PatternCandidate).count() == 1
    stored = db_session.get(ScanRun, scan.id)
    assert stored.scan_type == ScanType.AVWAP_PATTERN.value
    assert stored.long_candidates_count == 0
    assert stored.short_candidates_count == 0
