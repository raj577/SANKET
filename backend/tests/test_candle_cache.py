"""Daily candle fetch/cache behaviour and backfill job lifecycle."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.timeutils import IST, utcnow
from app.market_data.fyers_client import TOKEN_EXPIRED_MESSAGE, FyersError
from app.models.enums import ScanType
from app.models.market import CandleBackfillRun, InstrumentCandle
from app.models.scan import ScanCandidate, ScanRun
from app.services import candle_service

API = "/api/v1"
DAY = 86400


class RecordingClient:
    """Fake FYERS client that records history calls and returns fixed candles."""

    def __init__(self, *, days: list[date] | None = None, errors: list[Exception] | None = None):
        self.days = days or [date(2026, 11, 10), date(2026, 11, 11)]
        self.errors = list(errors or [])
        self.calls: list[dict] = []

    def history(self, symbol, *, resolution, range_from, range_to, date_format, cont_flag):
        self.calls.append(
            {
                "symbol": symbol,
                "resolution": resolution,
                "from": int(range_from),
                "to": int(range_to),
            }
        )
        if self.errors:
            raise self.errors.pop(0)
        return {
            "s": "ok",
            "candles": [
                [
                    int(datetime(d.year, d.month, d.day, tzinfo=IST).timestamp()),
                    100.0,
                    105.0,
                    95.0,
                    100.0 + index,
                    1000,
                ]
                for index, d in enumerate(self.days)
            ],
        }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def _fetcher(client, clock, **kwargs) -> candle_service.DailyCandleFetcher:
    return candle_service.DailyCandleFetcher(
        client, timezone="Asia/Kolkata", clock=clock.clock, sleep=clock.sleep, **kwargs
    )


def test_daily_candles_are_normalized_to_trade_dates():
    client = RecordingClient()
    clock = FakeClock()
    fetcher = _fetcher(client, clock, pause_seconds=0)
    candles = fetcher.fetch("NSE:INFY-EQ", date(2026, 11, 10), date(2026, 11, 11))

    assert [candle["trade_date"] for candle in candles] == [
        date(2026, 11, 10),
        date(2026, 11, 11),
    ]
    assert candles[0]["close"] == Decimal("100.0000")
    assert candles[0]["volume"] == 1000
    assert client.calls[0]["resolution"] == "D"


def test_chunking_covers_a_long_range_and_merges_a_one_day_tail():
    client = RecordingClient()
    clock = FakeClock()
    fetcher = _fetcher(client, clock, pause_seconds=0, chunk_days=120)

    fetcher.fetch("NSE:INFY-EQ", date(2026, 1, 1), date(2026, 4, 30))  # 120 days
    assert len(client.calls) == 1  # exact single chunk

    client.calls.clear()
    fetcher.fetch("NSE:INFY-EQ", date(2026, 1, 1), date(2026, 5, 2))  # 122 days
    assert len(client.calls) == 2  # 120 days + a 2 day remainder

    client.calls.clear()
    fetcher.fetch("NSE:INFY-EQ", date(2026, 1, 1), date(2026, 5, 1))  # 121 days
    assert len(client.calls) == 1  # the 1 day tail is folded into the first chunk
    assert client.calls[0]["to"] == int(
        datetime(2026, 5, 1, tzinfo=IST).timestamp()
    )


def test_requests_are_paced():
    client = RecordingClient()
    clock = FakeClock()
    fetcher = _fetcher(client, clock, pause_seconds=1.3, chunk_days=10)

    fetcher.fetch("NSE:INFY-EQ", date(2026, 11, 1), date(2026, 11, 25))

    assert len(client.calls) == 3
    assert clock.sleeps == [1.3, 1.3]


def test_rate_limit_is_retried_after_a_long_pause():
    client = RecordingClient(errors=[FyersError("FYERS request failed with status 429")])
    clock = FakeClock()
    fetcher = _fetcher(
        client,
        clock,
        pause_seconds=0,
        max_retries=1,
        rate_limit_backoff_seconds=60,
    )

    candles = fetcher.fetch("NSE:INFY-EQ", date(2026, 11, 10), date(2026, 11, 11))

    assert candles
    assert len(client.calls) == 2
    assert clock.sleeps == [60.0]


def test_expired_token_is_not_retried():
    client = RecordingClient(errors=[FyersError(TOKEN_EXPIRED_MESSAGE)])
    clock = FakeClock()
    fetcher = _fetcher(client, clock, pause_seconds=0, max_retries=2)

    with pytest.raises(FyersError, match="token expired"):
        fetcher.fetch("NSE:INFY-EQ", date(2026, 11, 10), date(2026, 11, 11))
    assert len(client.calls) == 1
    assert clock.sleeps == []


def test_upsert_updates_a_partial_candle_and_inserts_new_dates(db_session):
    db = db_session
    symbol = "NSE:INFY-EQ"
    first = [
        {
            "trade_date": date(2026, 11, 10),
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100"),
            "volume": 10,
        }
    ]
    assert candle_service.upsert_candles(db, symbol, first) == 1

    refreshed = [
        {
            "trade_date": date(2026, 11, 10),
            "open": Decimal("100"),
            "high": Decimal("106"),
            "low": Decimal("99"),
            "close": Decimal("105"),
            "volume": 20,
        },
        {
            "trade_date": date(2026, 11, 11),
            "open": Decimal("105"),
            "high": Decimal("107"),
            "low": Decimal("104"),
            "close": Decimal("106"),
            "volume": 30,
        },
    ]
    assert candle_service.upsert_candles(db, symbol, refreshed) == 2

    rows = db.query(InstrumentCandle).filter_by(symbol=symbol).order_by(
        InstrumentCandle.trade_date
    ).all()
    assert len(rows) == 2
    assert rows[0].close == Decimal("105.0000")
    assert rows[0].volume == 20
    assert rows[1].close == Decimal("106.0000")


class FakeFetcher:
    def __init__(self, mapping: dict[str, dict[date, float]], error: Exception | None = None):
        self.mapping = mapping
        self.error = error
        self.calls: list[str] = []

    def fetch(self, symbol: str, start: date, end: date):
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        closes = self.mapping.get(symbol, {})
        return [
            {
                "trade_date": day,
                "open": Decimal(str(close)),
                "high": Decimal(str(close)),
                "low": Decimal(str(close)),
                "close": Decimal(str(close)),
                "volume": 1,
            }
            for day, close in sorted(closes.items())
            if start <= day <= end
        ]

    def close(self) -> None:  # pragma: no cover - only used when owned
        pass


def _job(db, *, symbols: list[str], date_from: date, date_to: date) -> CandleBackfillRun:
    return candle_service.create_backfill(
        db, date_from=date_from, date_to=date_to, symbols=symbols
    )


def test_backfill_job_records_progress_and_candles(db_session):
    db = db_session
    job = _job(
        db,
        symbols=["NSE:INFY-EQ", "NSE:NIFTY50-INDEX"],
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 11),
    )
    fetcher = FakeFetcher(
        {
            "NSE:INFY-EQ": {date(2026, 11, 10): 100, date(2026, 11, 11): 102},
            "NSE:NIFTY50-INDEX": {date(2026, 11, 10): 24000, date(2026, 11, 11): 24100},
        }
    )

    candle_service.run_backfill_job(job.id, ["NSE:INFY-EQ", "NSE:NIFTY50-INDEX"], fetcher=fetcher)

    db.expire_all()
    stored = db.get(CandleBackfillRun, job.id)
    assert stored.status == "COMPLETED"
    assert stored.processed_symbols == 2
    assert stored.failed_symbols == 0
    assert stored.candles_written == 4
    assert stored.progress["percent"] == 100
    assert stored.progress["state"] == "finished"
    assert {entry["state"] for entry in stored.progress["symbols"]} == {"FETCHED"}
    assert db.query(InstrumentCandle).count() == 4


def test_backfill_aborts_on_expired_token_and_marks_remaining_symbols(db_session):
    db = db_session
    symbols = ["NSE:AAA-EQ", "NSE:BBB-EQ", "NSE:CCC-EQ"]
    job = _job(
        db, symbols=symbols, date_from=date(2026, 11, 10), date_to=date(2026, 11, 11)
    )

    candle_service.run_backfill_job(
        job.id, symbols, fetcher=FakeFetcher({}, error=FyersError(TOKEN_EXPIRED_MESSAGE))
    )

    db.expire_all()
    stored = db.get(CandleBackfillRun, job.id)
    assert stored.status == "FAILED"
    assert "token expired" in (stored.error_message or "")
    assert all(entry["state"] == "ERROR" for entry in stored.progress["symbols"])
    assert "Backfill stopped" in stored.progress["symbols"][1]["message"]


def test_one_symbol_failure_does_not_stop_the_rest(db_session):
    db = db_session
    symbols = ["NSE:INFY-EQ", "NSE:TCS-EQ"]
    job = _job(
        db, symbols=symbols, date_from=date(2026, 11, 10), date_to=date(2026, 11, 10)
    )

    class PartialFetcher(FakeFetcher):
        def fetch(self, symbol, start, end):
            if symbol == "NSE:TCS-EQ":
                raise FyersError("FYERS request failed with status 500")
            return super().fetch(symbol, start, end)

    candle_service.run_backfill_job(
        job.id,
        symbols,
        fetcher=PartialFetcher({"NSE:INFY-EQ": {date(2026, 11, 10): 100}}),
    )

    db.expire_all()
    stored = db.get(CandleBackfillRun, job.id)
    assert stored.status == "PARTIAL"
    assert stored.failed_symbols == 1
    states = {entry["symbol"]: entry["state"] for entry in stored.progress["symbols"]}
    assert states == {"NSE:INFY-EQ": "FETCHED", "NSE:TCS-EQ": "ERROR"}


def test_a_second_backfill_is_rejected_while_one_runs(db_session):
    db = db_session
    _job(
        db,
        symbols=["NSE:INFY-EQ"],
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
    )
    running = db.query(CandleBackfillRun).one()
    running.status = "RUNNING"
    running.updated_at = utcnow()
    db.commit()

    with pytest.raises(Exception) as excinfo:
        _job(
            db,
            symbols=["NSE:TCS-EQ"],
            date_from=date(2026, 11, 10),
            date_to=date(2026, 11, 10),
        )
    assert "already running" in str(excinfo.value)


def test_stale_running_backfill_is_closed_before_a_new_one(db_session):
    db = db_session
    _job(
        db,
        symbols=["NSE:INFY-EQ"],
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
    )
    stale = db.query(CandleBackfillRun).one()
    stale.status = "RUNNING"
    stale.updated_at = utcnow() - timedelta(hours=2)
    db.commit()

    fresh = _job(
        db,
        symbols=["NSE:TCS-EQ"],
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 10),
    )

    db.expire_all()
    closed = db.get(CandleBackfillRun, stale.id)
    assert closed.status == "FAILED"
    assert "did not finish" in (closed.error_message or "")
    assert db.get(CandleBackfillRun, fresh.id).status == "PENDING"


def test_backfill_api_stores_candles_and_feeds_the_report(
    client, admin_headers, db_session, monkeypatch
):
    db = db_session
    scan = ScanRun(scan_type=ScanType.OI.value, status="COMPLETED", total_symbols=1)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    db.add(
        ScanCandidate(
            scan_id=scan.id,
            symbol="INFY",
            direction="LONG",
            scan_ltp=Decimal("100"),
            score=Decimal("10"),
            grade="A",
            reason="",
            confirmation_count=1,
            scanned_at=datetime(2026, 11, 10, 10, 0, tzinfo=IST),
            status="PENDING",
        )
    )
    db.commit()

    fetcher = FakeFetcher(
        {
            "NSE:INFY-EQ": {date(2026, 11, 10): 100, date(2026, 11, 11): 108},
            "NSE:NIFTY50-INDEX": {
                date(2026, 11, 10): 24000,
                date(2026, 11, 11): 24100,
            },
        }
    )
    monkeypatch.setattr(candle_service, "_build_fetcher", lambda: fetcher)

    start = client.post(
        f"{API}/admin/performance/backfill",
        json={"date_from": "2026-11-10", "date_to": "2026-11-10", "forward_days": 1},
        headers=admin_headers,
    )
    assert start.status_code == 202, start.text

    latest = client.get(f"{API}/admin/performance/backfill/latest", headers=admin_headers)
    assert latest.status_code == 200, latest.text
    payload = latest.json()
    assert payload["status"] == "COMPLETED"
    assert payload["processed_symbols"] == 2
    assert payload["candles_written"] == 4

    report = client.get(
        f"{API}/admin/performance",
        params={"date_from": "2026-11-10", "date_to": "2026-11-10", "forward_days": 1},
        headers=admin_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["days"][0]["symbols"][0]["returns_pct"] == [8.0]
    assert body["missing_symbols"] == []


def test_backfill_requires_authentication(client):
    response = client.post(
        f"{API}/admin/performance/backfill", json={"date_from": "2026-11-10"}
    )
    assert response.status_code in {401, 403}
