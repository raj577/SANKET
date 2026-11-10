"""Price tracker worker behaviour with a fake FYERS client."""
from __future__ import annotations

from decimal import Decimal

from app.core.timeutils import utcnow
from app.models.scan import ScanCandidate, ScanRun
from app.models.signal import PublishedSignal
from app.services import settings_service
from app.workers.price_tracker_worker import run_once, to_fyers_symbol


class FakeClient:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    def ltp_map(self, symbols):
        self.calls.append(list(symbols))
        return {symbol: price for symbol, price in self.prices.items() if symbol in symbols}


class ExplodingClient:
    def ltp_map(self, symbols):  # pragma: no cover - must not be called
        raise AssertionError("quotes must not be requested when tracking is disabled")


def _create_signal(db_session, *, symbol="WIPRO", direction="LONG", entry=100, target=105, stop=95):
    scan = ScanRun(started_at=utcnow(), status="COMPLETED", total_symbols=1)
    db_session.add(scan)
    db_session.flush()
    candidate = ScanCandidate(
        scan_id=scan.id,
        symbol=symbol,
        direction=direction,
        scan_ltp=Decimal(str(entry)),
        score=Decimal("500"),
        grade="B",
        reason="test",
        confirmation_count=3,
        scanned_at=utcnow(),
    )
    db_session.add(candidate)
    db_session.flush()
    signal = PublishedSignal(
        candidate_id=candidate.id,
        symbol=symbol,
        direction=direction,
        scan_ltp=Decimal(str(entry)),
        entry_price=Decimal(str(entry)),
        target_price=Decimal(str(target)),
        stop_loss=Decimal(str(stop)),
        published_at=utcnow(),
        status="ACTIVE",
    )
    db_session.add(signal)
    db_session.commit()
    return signal


def _enable_tracking(db_session):
    settings_service.update_values(
        db_session,
        {"market_data": {"tracking_enabled": True, "persist_interval_seconds": 60}},
    )
    db_session.commit()


def test_symbol_mapping():
    assert to_fyers_symbol("NIFTY") == "NSE:NIFTY50-INDEX"
    assert to_fyers_symbol("banknifty") == "NSE:NIFTYBANK-INDEX"
    assert to_fyers_symbol("WIPRO") == "NSE:WIPRO-EQ"
    assert to_fyers_symbol("M&M") == "NSE:M&M-EQ"


def test_tracker_updates_price_and_detects_target(client, db_session):
    signal = _create_signal(db_session)
    _enable_tracking(db_session)
    fake = FakeClient({"NSE:WIPRO-EQ": 106.0})

    result = run_once(db_session, fake, now=utcnow())
    assert result["updated"] == 1
    assert fake.calls == [["NSE:WIPRO-EQ"]]
    assert len(result["events"]) == 1
    assert result["events"][0]["event"] == "TARGET_HIT"
    assert result["quotes"]["WIPRO"] == 106.0

    db_session.expire_all()
    refreshed = db_session.get(PublishedSignal, signal.id)
    assert refreshed.status == "TARGET_HIT"
    assert refreshed.current_ltp == Decimal("106.0000")
    assert refreshed.target_hit_at is not None
    assert refreshed.closed_at is not None

    # Terminal signals are not updated again.
    again = run_once(db_session, FakeClient({"NSE:WIPRO-EQ": 120.0}), now=utcnow())
    assert again["updated"] == 0
    assert again["events"] == []


def test_tracker_leaves_signal_untouched_when_quote_is_missing(client, db_session):
    signal = _create_signal(db_session)
    _enable_tracking(db_session)

    result = run_once(db_session, FakeClient({}), now=utcnow())
    assert result["updated"] == 0
    assert result["quotes"] == {}

    db_session.expire_all()
    refreshed = db_session.get(PublishedSignal, signal.id)
    assert refreshed.status == "ACTIVE"
    assert refreshed.current_ltp is None
    assert refreshed.price_updated_at is None


def test_tracking_disabled_skips_provider_call(client, db_session):
    _create_signal(db_session)
    result = run_once(db_session, ExplodingClient(), tracking_enabled=False)
    assert result["skipped"] == "tracking_disabled"
