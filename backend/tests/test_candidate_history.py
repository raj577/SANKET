"""Repeat history for OI candidates: previous scan, previous scan days, flips."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import ScanType
from app.models.scan import ScanCandidate, ScanRun
from app.services import candidate_history_service

API = "/api/v1"


def _scan(db, started_at: datetime, *, scan_type: str = ScanType.OI.value) -> ScanRun:
    scan = ScanRun(
        scan_type=scan_type,
        status="COMPLETED",
        total_symbols=1,
        started_at=started_at,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def _candidate(db, scan: ScanRun, symbol: str, direction: str) -> ScanCandidate:
    candidate = ScanCandidate(
        scan_id=scan.id,
        symbol=symbol,
        direction=direction,
        scan_ltp=Decimal(100),
        score=Decimal(10),
        grade="A",
        reason="",
        confirmation_count=1,
        scanned_at=scan.started_at,
        status="PENDING",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _history(db, candidate: ScanCandidate) -> dict:
    return candidate_history_service.history_map(db, [candidate])[candidate.id]


def _seed(db):
    """Two scans on 2026-11-10, one on the 11th, one on the 12th (all IST mornings)."""
    scan_a = _scan(db, datetime(2026, 11, 10, 4, 30, tzinfo=UTC))  # 10:00 IST
    scan_b = _scan(db, datetime(2026, 11, 10, 9, 0, tzinfo=UTC))  # 14:30 IST
    scan_c = _scan(db, datetime(2026, 11, 11, 4, 30, tzinfo=UTC))
    scan_d = _scan(db, datetime(2026, 11, 12, 4, 30, tzinfo=UTC))

    _candidate(db, scan_a, "ALPHA", "SHORT")
    _candidate(db, scan_a, "BETA", "LONG")

    _candidate(db, scan_b, "ALPHA", "LONG")
    _candidate(db, scan_b, "BETA", "LONG")
    _candidate(db, scan_b, "GAMMA", "LONG")

    _candidate(db, scan_c, "ALPHA", "SHORT")
    _candidate(db, scan_c, "BETA", "LONG")

    delta_alpha = _candidate(db, scan_d, "ALPHA", "LONG")
    delta_beta = _candidate(db, scan_d, "BETA", "LONG")
    delta_delta = _candidate(db, scan_d, "DELTA", "SHORT")
    return {
        "a": scan_a,
        "b": scan_b,
        "c": scan_c,
        "d": scan_d,
        "alpha": delta_alpha,
        "beta": delta_beta,
        "delta": delta_delta,
    }


def test_history_marks_previous_scan_and_the_two_previous_scan_days(db_session):
    seed = _seed(db_session)
    db = db_session

    alpha_history = _history(db, seed["alpha"])
    assert alpha_history["in_previous_scan"] is True
    assert alpha_history["in_last_2_days"] is True
    assert alpha_history["previous_direction"] == "SHORT"
    assert alpha_history["short_to_long"] is True
    assert alpha_history["previous_seen_at"] == seed["c"].started_at

    beta_history = _history(db, seed["beta"])
    assert beta_history["in_previous_scan"] is True
    assert beta_history["in_last_2_days"] is True
    assert beta_history["previous_direction"] == "LONG"
    assert beta_history["short_to_long"] is False

    delta_history = _history(db, seed["delta"])
    assert delta_history == {
        "in_previous_scan": False,
        "in_last_2_days": False,
        "previous_direction": None,
        "short_to_long": False,
        "previous_seen_at": None,
    }

    # The earliest scan has no history at all.
    first = db.query(ScanCandidate).filter(ScanCandidate.scan_id == seed["a"].id).first()
    assert _history(db, first)["in_previous_scan"] is False
    assert _history(db, first)["previous_seen_at"] is None


def test_same_day_second_scan_is_a_repeat_but_not_a_previous_day(db_session):
    seed = _seed(db_session)
    first = (
        db_session.query(ScanCandidate)
        .filter(ScanCandidate.scan_id == seed["b"].id, ScanCandidate.symbol == "ALPHA")
        .one()
    )
    history = candidate_history_service.history_map(db_session, [first])[first.id]
    assert history["in_previous_scan"] is True
    assert history["in_last_2_days"] is False
    assert history["previous_direction"] is None
    assert history["short_to_long"] is False
    assert history["previous_seen_at"] is not None


def test_pattern_scans_never_supply_history(db_session):
    db = db_session
    pattern_scan = _scan(
        db,
        datetime(2026, 11, 9, 4, 30, tzinfo=UTC),
        scan_type=ScanType.AVWAP_PATTERN.value,
    )
    _candidate(db, pattern_scan, "ALPHA", "SHORT")
    scan = _scan(db, datetime(2026, 11, 10, 4, 30, tzinfo=UTC))
    alpha = _candidate(db, scan, "ALPHA", "LONG")

    history = _history(db, alpha)
    assert history["in_previous_scan"] is False
    assert history["in_last_2_days"] is False
    assert history["short_to_long"] is False


def test_list_api_annotates_and_filters_by_repeat(client, admin_headers, db_session):
    seed = _seed(db_session)
    scan_d = seed["d"]

    everything = client.get(
        f"{API}/admin/candidates",
        params={"scan_id": str(scan_d.id), "page_size": 200},
        headers=admin_headers,
    )
    assert everything.status_code == 200, everything.text
    items = {row["symbol"]: row for row in everything.json()["items"]}
    assert everything.json()["total"] == 3
    assert items["ALPHA"]["history"]["short_to_long"] is True
    assert items["BETA"]["history"]["in_previous_scan"] is True
    assert items["DELTA"]["history"]["in_previous_scan"] is False
    assert items["DELTA"]["history"]["previous_seen_at"] is None

    last_two_scans = client.get(
        f"{API}/admin/candidates",
        params={"scan_id": str(scan_d.id), "repeat": "last_2_scans"},
        headers=admin_headers,
    )
    assert last_two_scans.status_code == 200, last_two_scans.text
    assert last_two_scans.json()["total"] == 2
    assert {row["symbol"] for row in last_two_scans.json()["items"]} == {"ALPHA", "BETA"}

    two_days = client.get(
        f"{API}/admin/candidates",
        params={"scan_id": str(scan_d.id), "repeat": "last_2_days"},
        headers=admin_headers,
    )
    assert two_days.status_code == 200
    assert two_days.json()["total"] == 2

    flip = client.get(
        f"{API}/admin/candidates",
        params={"scan_id": str(scan_d.id), "repeat": "short_to_long"},
        headers=admin_headers,
    )
    assert flip.status_code == 200
    assert [row["symbol"] for row in flip.json()["items"]] == ["ALPHA"]

    # Filtering keeps pagination honest: one page of one row, two total.
    paged = client.get(
        f"{API}/admin/candidates",
        params={"scan_id": str(scan_d.id), "repeat": "last_2_scans", "page_size": 1},
        headers=admin_headers,
    )
    assert paged.status_code == 200
    assert paged.json()["total"] == 2
    assert len(paged.json()["items"]) == 1

    invalid = client.get(
        f"{API}/admin/candidates",
        params={"repeat": "all_repeats"},
        headers=admin_headers,
    )
    assert invalid.status_code == 422


def test_candidate_detail_carries_history(client, admin_headers, db_session):
    seed = _seed(db_session)
    detail = client.get(f"{API}/admin/candidates/{seed['alpha'].id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    history = detail.json()["history"]
    assert history["short_to_long"] is True
    assert history["previous_direction"] == "SHORT"
    assert history["in_previous_scan"] is True
