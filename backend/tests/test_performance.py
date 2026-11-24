"""Day-wise performance report: returns, alignment, coverage and API shape."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.core.timeutils import IST
from app.models.enums import ScanType
from app.models.market import InstrumentCandle
from app.models.scan import ScanCandidate, ScanRun
from app.services import performance_service

API = "/api/v1"


def _dt(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=IST)


def _scan(db, *, scan_type: str = ScanType.OI.value) -> ScanRun:
    scan = ScanRun(scan_type=scan_type, status="COMPLETED", total_symbols=1)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def _candidate(
    db,
    scan: ScanRun,
    *,
    symbol: str,
    direction: str,
    scan_ltp: float,
    scanned_at: datetime,
    status: str = "PENDING",
) -> ScanCandidate:
    candidate = ScanCandidate(
        scan_id=scan.id,
        symbol=symbol,
        direction=direction,
        scan_ltp=Decimal(str(scan_ltp)),
        score=Decimal("10"),
        grade="A",
        reason="",
        confirmation_count=1,
        scanned_at=scanned_at,
        status=status,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _candle(db, symbol: str, day: date, close: float) -> None:
    db.add(
        InstrumentCandle(
            symbol=symbol,
            trade_date=day,
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=1000,
            source="FYERS",
        )
    )


def _benchmark(db, days: list[date]) -> None:
    for day in days:
        _candle(db, "NSE:NIFTY50-INDEX", day, 24000)


def test_returns_are_direction_adjusted_and_aligned(db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    _candidate(
        db,
        scan,
        symbol="TCS",
        direction="SHORT",
        scan_ltp=200,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    _benchmark(
        db,
        [date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13)],
    )
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 11), 110)
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 12), 90)
    _candle(db, "NSE:TCS-EQ", date(2026, 11, 11), 190)
    _candle(db, "NSE:TCS-EQ", date(2026, 11, 12), 210)
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
        forward_days=2,
        now=_dt(date(2026, 11, 13), 20),
    )

    assert report["totals"]["filtered"] == 2
    assert report["totals"]["scan_days"] == 1
    day = report["days"][0]
    assert day["day"] == date(2026, 11, 10)
    assert day["long_count"] == 1 and day["short_count"] == 1
    assert [offset["trade_date"] for offset in day["offsets"]] == [
        date(2026, 11, 11),
        date(2026, 11, 12),
    ]

    rows = {row["symbol"]: row for row in day["symbols"]}
    # LONG 100 -> 110 is +10%, 100 -> 90 is -10%.
    assert rows["INFY"]["returns_pct"] == [10.0, -10.0]
    # SHORT 200 -> 190 is +5% in the scanner's direction, 200 -> 210 is -5%.
    assert rows["TCS"]["returns_pct"] == [5.0, -5.0]
    assert rows["INFY"]["coverage"] == "COMPLETE"

    d1 = day["offsets"][0]
    assert d1["n"] == 2
    assert d1["avg_return_pct"] == 7.5  # (10 + 5) / 2
    assert d1["win_rate_pct"] == 100.0
    assert d1["best_return_pct"] == 10.0
    assert d1["worst_return_pct"] == 5.0


def test_weekend_scan_aligns_to_next_trading_day(db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 14), 12),  # Saturday
    )
    _benchmark(
        db,
        [date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 17)],
    )
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 16), 105)
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 17), 95)
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 14),
        date_to=date(2026, 11, 14),
        forward_days=2,
        now=_dt(date(2026, 11, 18), 20),
    )

    offsets = report["days"][0]["offsets"]
    assert [offset["trade_date"] for offset in offsets] == [
        date(2026, 11, 16),
        date(2026, 11, 17),
    ]
    assert report["days"][0]["symbols"][0]["returns_pct"] == [5.0, -5.0]


def test_today_candle_is_not_used_for_forward_returns(db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 13)),
    )
    _benchmark(db, [date(2026, 11, 13), date(2026, 11, 16)])
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 16), 105)
    db.commit()

    # Nov 16 is "today", so its still-forming candle must not become D+1.
    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 13),
        date_to=date(2026, 11, 13),
        forward_days=1,
        now=_dt(date(2026, 11, 16), 11),
    )

    assert report["days"][0]["offsets"] == []
    assert report["days"][0]["pending"] is True
    assert report["pending_days"] == 1
    assert report["days"][0]["symbols"][0]["coverage"] == "PENDING"


def test_an_empty_cache_is_missing_data_not_a_pending_session(db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
        forward_days=1,
        now=_dt(date(2026, 11, 20), 20),
    )

    assert report["days"][0]["pending"] is False
    assert report["pending_days"] == 0
    assert report["missing_symbols"] == ["NSE:INFY-EQ"]
    assert report["cache"]["candles"] == 0


def test_repeated_scans_of_a_symbol_collapse_to_the_latest(db_session):
    db = db_session
    first_scan = _scan(db)
    _candidate(
        db,
        first_scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10), 10),
    )
    second_scan = _scan(db)
    _candidate(
        db,
        second_scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=120,
        scanned_at=_dt(date(2026, 11, 10), 14),
    )
    _benchmark(db, [date(2026, 11, 11)])
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 11), 132)
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
        forward_days=1,
        now=_dt(date(2026, 11, 12), 20),
    )

    day = report["days"][0]
    assert day["filtered"] == 1
    assert day["duplicates_collapsed"] == 1
    assert day["symbols"][0]["scan_ltp"] == Decimal("120.0000")
    # 120 -> 132 = +10%, proving the later scan was the entry.
    assert day["symbols"][0]["returns_pct"] == [10.0]


def test_missing_candles_are_reported_not_invented(db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="NEWLIST",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    _benchmark(db, [date(2026, 11, 11)])
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
        forward_days=1,
        now=_dt(date(2026, 11, 12), 20),
    )

    row = report["days"][0]["symbols"][0]
    assert row["coverage"] == "NO_DATA"
    assert row["returns_pct"] == [None]
    assert report["missing_symbols"] == ["NSE:NEWLIST-EQ"]
    assert report["days"][0]["offsets"][0]["n"] == 0


def test_pattern_scans_do_not_leak_into_the_oi_report(db_session):
    db = db_session
    pattern_scan = _scan(db, scan_type=ScanType.AVWAP_PATTERN.value)
    _candidate(
        db,
        pattern_scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    _benchmark(db, [date(2026, 11, 11)])
    db.commit()

    report = performance_service.build_report(
        db,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
        forward_days=1,
        now=_dt(date(2026, 11, 12), 20),
    )

    assert report["days"] == []
    assert report["totals"]["filtered"] == 0


def test_status_filter_separates_approved_from_the_rest(db_session):
    db = db_session
    scan = _scan(db)
    entries = [
        ("INFY", "APPROVED", 110),
        ("TCS", "PUBLISHED", 120),
        ("WIPRO", "PENDING", 90),
        ("SBIN", "REJECTED", 80),
    ]
    for symbol, status, _close in entries:
        _candidate(
            db,
            scan,
            symbol=symbol,
            direction="LONG",
            scan_ltp=100,
            scanned_at=_dt(date(2026, 11, 10)),
            status=status,
        )
    _benchmark(db, [date(2026, 11, 11)])
    for symbol, _status, close in entries:
        _candle(db, f"NSE:{symbol}-EQ", date(2026, 11, 11), close)
    db.commit()

    def run(status: str | None):
        return performance_service.build_report(
            db,
            date_from=date(2026, 11, 10),
            date_to=date(2026, 11, 10),
            forward_days=1,
            status_filter=status,
            now=_dt(date(2026, 11, 12), 20),
        )

    everything = run("all")
    assert everything["status_filter"] == "all"
    assert everything["totals"]["filtered"] == 4
    # (10 + 20 - 10 - 20) / 4
    assert everything["days"][0]["offsets"][0]["avg_return_pct"] == 0.0

    approved = run("approved")
    assert approved["status_filter"] == "approved"
    assert approved["totals"]["filtered"] == 2
    assert {row["symbol"] for row in approved["days"][0]["symbols"]} == {"INFY", "TCS"}
    assert approved["days"][0]["long_count"] == 2
    # (10 + 20) / 2: approved names only
    assert approved["days"][0]["offsets"][0]["avg_return_pct"] == 15.0
    assert approved["days"][0]["offsets"][0]["n"] == 2

    unapproved = run("not_approved")
    assert unapproved["status_filter"] == "not_approved"
    assert unapproved["totals"]["filtered"] == 2
    assert {row["symbol"] for row in unapproved["days"][0]["symbols"]} == {"WIPRO", "SBIN"}
    # (-10 + -20) / 2
    assert unapproved["days"][0]["offsets"][0]["avg_return_pct"] == -15.0

    # Omitting the filter keeps the previous behaviour.
    assert run(None)["totals"]["filtered"] == 4


def test_report_api_status_filter_and_validation(client, admin_headers, db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
        status="APPROVED",
    )
    _candidate(
        db,
        scan,
        symbol="WIPRO",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
        status="PENDING",
    )
    _benchmark(db, [date(2026, 11, 11)])
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 11), 108)
    _candle(db, "NSE:WIPRO-EQ", date(2026, 11, 11), 92)
    db.commit()

    response = client.get(
        f"{API}/admin/performance",
        params={
            "date_from": "2026-11-10",
            "date_to": "2026-11-10",
            "forward_days": 1,
            "status": "approved",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status_filter"] == "approved"
    assert payload["totals"]["filtered"] == 1
    assert [row["symbol"] for row in payload["days"][0]["symbols"]] == ["INFY"]

    everything = client.get(
        f"{API}/admin/performance",
        params={"date_from": "2026-11-10", "date_to": "2026-11-10", "forward_days": 1},
        headers=admin_headers,
    )
    assert everything.status_code == 200
    assert everything.json()["status_filter"] == "all"
    assert everything.json()["totals"]["filtered"] == 2

    invalid = client.get(
        f"{API}/admin/performance",
        params={"status": "maybe"},
        headers=admin_headers,
    )
    assert invalid.status_code == 422


def test_report_api_returns_seeded_day(client, admin_headers, db_session):
    db = db_session
    scan = _scan(db)
    _candidate(
        db,
        scan,
        symbol="INFY",
        direction="LONG",
        scan_ltp=100,
        scanned_at=_dt(date(2026, 11, 10)),
    )
    _benchmark(db, [date(2026, 11, 11)])
    _candle(db, "NSE:INFY-EQ", date(2026, 11, 11), 108)
    db.commit()

    response = client.get(
        f"{API}/admin/performance",
        params={
            "date_from": "2026-11-10",
            "date_to": "2026-11-10",
            "forward_days": 1,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["date_from"] == "2026-11-10"
    assert payload["totals"]["filtered"] == 1
    assert payload["days"][0]["day"] == "2026-11-10"
    assert payload["cache"]["symbols"] >= 1


def test_report_api_rejects_an_inverted_window(client, admin_headers):
    response = client.get(
        f"{API}/admin/performance",
        params={"date_from": "2026-11-12", "date_to": "2026-11-10"},
        headers=admin_headers,
    )
    assert response.status_code in {400, 422}


def test_forward_days_bounds_are_validated(client, admin_headers):
    response = client.get(
        f"{API}/admin/performance",
        params={"date_from": "2026-11-10", "date_to": "2026-11-10", "forward_days": 99},
        headers=admin_headers,
    )
    assert response.status_code in {400, 422}
