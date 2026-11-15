"""Admin API for the AVWAP pattern scanner.

Covers admin authentication, request validation, the OI/pattern split on the
scan list, pattern scan detail enrichment and the approve/reject workflow.
FYERS is never contacted: the background job is replaced with a fake history
service, and the provider check is stubbed.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import CandidateStatus, ScanType
from app.models.scan import PatternCandidate, ScanRun
from app.services import pattern_scan_service

from .conftest import API
from .pattern_fixtures import FakeHistoryService, ist, make_frame, make_instrument

NOW = ist(2026, 11, 4, 16, 0)
SYMBOL = "NSE:NIFTY26NOVFUT"


@pytest.fixture()
def pattern_provider(monkeypatch):
    """Pretend FYERS is connected and run the real job offline."""
    real_job = pattern_scan_service.run_scan_job

    def fake_job(scan_id, symbols, timeframe, include_index, current_expiry_only):
        real_job(
            scan_id,
            symbols,
            timeframe,
            include_index,
            current_expiry_only,
            history_service=FakeHistoryService(make_frame(pattern_count=3)),
            instruments=[make_instrument(SYMBOL, "NIFTY")],
            now=NOW,
        )

    monkeypatch.setattr(pattern_scan_service, "provider_ready", lambda: (True, ""))
    monkeypatch.setattr(pattern_scan_service, "run_scan_job", fake_job)
    return monkeypatch


def _start(client, headers, **payload) -> dict:
    response = client.post(
        f"{API}/admin/scans/pattern", headers=headers, json=payload
    )
    assert response.status_code == 202, response.text
    return response.json()


# ------------------------------------------------------------------- auth


def test_pattern_scan_requires_admin(client):
    response = client.post(f"{API}/admin/scans/pattern", json={})
    assert response.status_code == 401


def test_pattern_scan_detail_requires_admin(client):
    response = client.get(f"{API}/admin/scans/{uuid.uuid4()}")
    assert response.status_code == 401


def test_pattern_candidate_review_requires_admin(client):
    candidate_id = uuid.uuid4()
    approve = client.post(f"{API}/admin/pattern-candidates/{candidate_id}/approve")
    reject = client.post(
        f"{API}/admin/pattern-candidates/{candidate_id}/reject", json={}
    )
    assert approve.status_code == 401
    assert reject.status_code == 401


# ------------------------------------------------------- provider readiness


def test_unconfigured_fyers_is_reported_as_conflict(client, admin_headers):
    """The test environment has no FYERS credentials."""
    response = client.post(
        f"{API}/admin/scans/pattern", headers=admin_headers, json={}
    )
    assert response.status_code == 409
    assert response.json()["detail"].startswith("FYERS is not configured")


# --------------------------------------------------------------- validation


def test_unsupported_timeframe_is_rejected(client, admin_headers, pattern_provider):
    response = client.post(
        f"{API}/admin/scans/pattern",
        headers=admin_headers,
        json={"timeframe": "7"},
    )
    assert response.status_code == 422
    assert "Unsupported timeframe" in response.json()["detail"]


def test_invalid_symbol_characters_are_rejected(
    client, admin_headers, pattern_provider
):
    response = client.post(
        f"{API}/admin/scans/pattern",
        headers=admin_headers,
        json={"symbols": ["NSE:NIFTY; DROP TABLE"]},
    )
    assert response.status_code == 422
    assert "Invalid symbol" in response.json()["detail"]


def test_symbol_limit_is_enforced(client, admin_headers, pattern_provider):
    response = client.post(
        f"{API}/admin/scans/pattern",
        headers=admin_headers,
        json={"symbols": [f"NSE:TEST{index}26NOVFUT" for index in range(30)]},
    )
    assert response.status_code == 422
    assert "At most" in response.json()["detail"]


def test_default_timeframe_is_used_when_omitted(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    assert body["timeframe"] == "60"


# ------------------------------------------------------------- scan lifecycle


def test_pattern_scan_is_queued_and_persisted(
    client, admin_headers, pattern_provider, db_session
):
    body = _start(client, admin_headers, symbols=[SYMBOL], timeframe="15")

    assert body["scan_type"] == ScanType.AVWAP_PATTERN.value
    assert body["timeframe"] == "15"
    # 202 Accepted: the run is queued and the background job owns completion.
    assert body["status"] == "PENDING"
    assert body["long_candidates_count"] == 0
    assert body["short_candidates_count"] == 0

    finished = client.get(f"{API}/admin/scans/{body['id']}", headers=admin_headers)
    assert finished.status_code == 200
    assert finished.json()["status"] == "COMPLETED"

    scan = db_session.get(ScanRun, uuid.UUID(body["id"]))
    assert scan is not None
    assert scan.scan_type == ScanType.AVWAP_PATTERN.value
    assert scan.timeframe == "15"
    assert scan.scanner_version == "avwap-pattern-1.0.0"
    assert scan.scanner_config["detector"]["max_close_above_pct"] == 0.005

    candidates = db_session.query(PatternCandidate).all()
    assert len(candidates) == 1
    assert candidates[0].status == CandidateStatus.PENDING.value


def test_scan_list_separates_oi_and_pattern_runs(
    client, admin_headers, pattern_provider, db_session
):
    _start(client, admin_headers, symbols=[SYMBOL])

    from datetime import datetime, timezone

    db_session.add(
        ScanRun(
            started_at=datetime.now(timezone.utc),
            status="COMPLETED",
            scan_type=ScanType.OI.value,
            trigger="collector",
        )
    )
    db_session.commit()

    default = client.get(f"{API}/admin/scans", headers=admin_headers)
    assert default.status_code == 200
    # The OI contract is unchanged: the default listing is OI-only.
    assert default.json()["total"] == 1
    assert default.json()["items"][0]["scan_type"] == ScanType.OI.value

    pattern_only = client.get(
        f"{API}/admin/scans",
        headers=admin_headers,
        params={"scan_type": ScanType.AVWAP_PATTERN.value},
    )
    assert pattern_only.status_code == 200
    assert pattern_only.json()["total"] == 1
    assert pattern_only.json()["items"][0]["scan_type"] == ScanType.AVWAP_PATTERN.value


def test_scan_detail_returns_pattern_candidates_and_config(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    detail = client.get(f"{API}/admin/scans/{body['id']}", headers=admin_headers)
    assert detail.status_code == 200
    payload = detail.json()

    assert payload["scan_type"] == ScanType.AVWAP_PATTERN.value
    assert payload["timeframe"] == "60"
    assert payload["pattern_config"]["max_body_ratio"] == 0.35
    assert payload["pattern_summary"]["matches"] == 1
    assert payload["pattern_summary"]["timeframe"] == "60"

    candidates = payload["pattern_candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["symbol"] == SYMBOL
    assert candidate["underlying"] == "NIFTY"
    assert candidate["timeframe"] == "60"
    assert candidate["pattern_type"] == "AVWAP CONSOLIDATION"
    assert candidate["candle_count"] == 3
    assert candidate["last_price"]
    assert candidate["avwap"]
    assert candidate["distance_pct"]
    assert candidate["avg_body_ratio"]
    assert candidate["max_body_ratio"]
    assert candidate["window_range_pct"]
    assert candidate["touched"] is True
    assert candidate["pattern_end"]
    assert candidate["detector_metadata"]["pattern_type"] == "AVWAP CONSOLIDATION"
    assert "confidence" not in candidate
    assert "score" not in candidate


def test_scan_detail_includes_progress_and_symbol_list(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    detail = client.get(f"{API}/admin/scans/{body['id']}", headers=admin_headers)
    payload = detail.json()

    progress = payload["pattern_progress"]
    assert progress["state"] == "finished"
    assert progress["processed"] == 1
    assert progress["total"] == 1
    assert progress["percent"] == 100
    assert progress["matched"] == 1
    assert progress["failed"] == 0

    symbols = payload["pattern_symbols"]
    assert [entry["symbol"] for entry in symbols] == [SYMBOL]
    assert symbols[0]["status"] == "MATCHED"
    assert symbols[0]["pattern_type"] == "AVWAP CONSOLIDATION"
    assert symbols[0]["underlying"] == "NIFTY"
    assert symbols[0]["candles"] == 43
    assert symbols[0]["last_price"]


def test_oi_scan_detail_has_no_pattern_payload(
    client, admin_headers, sample_csv_bytes, db_session
):
    from .conftest import COLLECTOR_HEADERS

    scan_id = str(uuid.uuid4())
    client.post(
        f"{API}/collector/scans",
        headers=COLLECTOR_HEADERS,
        json={"scan_id": scan_id, "total_symbols": 1},
    )
    client.post(
        f"{API}/collector/scans/{scan_id}/csv",
        headers=COLLECTOR_HEADERS,
        files={"file": ("sensibull.csv", sample_csv_bytes, "text/csv")},
    )

    detail = client.get(f"{API}/admin/scans/{scan_id}", headers=admin_headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["scan_type"] == ScanType.OI.value
    assert payload["pattern_candidates"] == []
    assert payload["pattern_summary"] is None
    assert payload["pattern_config"] is None
    assert payload["pattern_progress"] is None
    assert payload["pattern_symbols"] == []


# ------------------------------------------------------------- review flow


def test_approve_and_reject_pattern_candidates(
    client, admin_headers, pattern_provider, db_session
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    detail = client.get(f"{API}/admin/scans/{body['id']}", headers=admin_headers)
    candidate_id = detail.json()["pattern_candidates"][0]["id"]

    approved = client.post(
        f"{API}/admin/pattern-candidates/{candidate_id}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == CandidateStatus.APPROVED.value

    rejected = client.post(
        f"{API}/admin/pattern-candidates/{candidate_id}/reject",
        headers=admin_headers,
        json={"reason": "not tradable today"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == CandidateStatus.REJECTED.value
    assert rejected.json()["reason"]

    listing = client.get(
        f"{API}/admin/pattern-candidates",
        headers=admin_headers,
        params={"status": "REJECTED"},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_unknown_pattern_candidate_returns_not_found(client, admin_headers):
    unknown = uuid.uuid4()
    approve = client.post(
        f"{API}/admin/pattern-candidates/{unknown}/approve", headers=admin_headers
    )
    reject = client.post(
        f"{API}/admin/pattern-candidates/{unknown}/reject",
        headers=admin_headers,
        json={},
    )
    assert approve.status_code == 404
    assert reject.status_code == 404


def test_pattern_candidate_cannot_be_published_as_an_oi_signal(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    detail = client.get(f"{API}/admin/scans/{body['id']}", headers=admin_headers)
    candidate_id = detail.json()["pattern_candidates"][0]["id"]

    published = client.post(
        f"{API}/admin/candidates/{candidate_id}/publish",
        headers=admin_headers,
        json={"entry_price": "100", "target_price": "105", "stop_loss": "97"},
    )
    assert published.status_code == 409
    assert "review-only" in published.json()["detail"]

    # An id that exists nowhere is still a plain 404, as before.
    missing = client.post(
        f"{API}/admin/candidates/{uuid.uuid4()}/publish",
        headers=admin_headers,
        json={"entry_price": "100", "target_price": "105", "stop_loss": "97"},
    )
    assert missing.status_code == 404


def test_pattern_candidate_list_filters_by_scan_and_type(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])

    by_scan = client.get(
        f"{API}/admin/pattern-candidates",
        headers=admin_headers,
        params={"scan_id": body["id"]},
    )
    assert by_scan.status_code == 200
    assert by_scan.json()["total"] == 1

    wrong_type = client.get(
        f"{API}/admin/pattern-candidates",
        headers=admin_headers,
        params={"pattern_type": "AVWAP TOUCH"},
    )
    assert wrong_type.status_code == 200
    assert wrong_type.json()["total"] == 0


def test_scan_start_is_audited(
    client, admin_headers, pattern_provider
):
    body = _start(client, admin_headers, symbols=[SYMBOL])
    logs = client.get(
        f"{API}/admin/audit", headers=admin_headers, params={"action": "SCAN_STARTED"}
    )
    assert logs.status_code == 200
    entries = logs.json()["items"]
    assert any(entry["entity_id"] == body["id"] for entry in entries)
