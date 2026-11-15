"""Historical candle retrieval and the NSE futures instrument universe.

The FYERS transport is replaced by a fake client, so no test touches the
network or the real token store.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pandas as pd
import pytest

from app.market_data.fyers_client import FyersError
from app.scanner.patterns.candles import NoMarketDataError
from app.scanner.patterns.detector import PatternDetector
from app.scanner.patterns.models import PatternConfig
from app.scanner.patterns.history import (
    InstrumentMasterError,
    InstrumentMasterProvider,
    PatternHistoryService,
    parse_instrument_master,
    resolve_instrument,
    select_active_futures,
    to_instruments,
)

from .pattern_fixtures import add_indicators, make_frame

TZ = "Asia/Kolkata"
EPOCH = 1730610900  # 2024-11-03 09:15 IST


class FakeFyersClient:
    """Records history calls and returns fixed candle rows."""

    def __init__(self, rows=None, *, error: Exception | None = None, errors=None):
        self.rows = list(rows) if rows is not None else []
        self.error = error
        self.errors = list(errors or [])
        self.calls: list[dict[str, object]] = []

    def history(self, symbol, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        if self.errors:
            raise self.errors.pop(0)
        if self.error is not None:
            raise self.error
        return {"s": "ok", "candles": [list(row) for row in self.rows]}


class _FakeClock:
    """Deterministic replacement for the ``time`` module used by the service."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _rows(count: int = 3) -> list[list[float]]:
    return [
        [EPOCH + index * 3600, 100.0 + index, 101.0 + index, 99.0 + index, 100.5 + index, 1000.0]
        for index in range(count)
    ]


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + months
    return date(month_index // 12, month_index % 12 + 1, 1)


_TODAY = date.today()
_NEAR = _add_months(_TODAY, 1)
_FAR = _add_months(_TODAY, 2)
_EXPIRED = _add_months(_TODAY, -2)


def _symbol(underlying: str, which: str) -> str:
    expiry = {"near": _NEAR, "far": _FAR, "expired": _EXPIRED}[which]
    return f"NSE:{underlying}{expiry:%y%b}FUT".upper()


def _master_rows() -> list[dict[str, str]]:
    def row(symbol: str, underlying: str, expiry: date, description: str) -> dict[str, str]:
        cells = [""] * 14
        cells[0] = "101000000000001"
        cells[1] = description
        cells[2] = "50"
        cells[3] = "0.05"
        cells[8] = _epoch(expiry)
        cells[9] = symbol
        cells[13] = underlying
        return cells

    near = _symbol("NIFTY", "near")
    far = _symbol("NIFTY", "far")
    expired = _symbol("NIFTY", "expired")
    bank_near = _symbol("BANKNIFTY", "near")

    return [
        row(near, "NIFTY", _NEAR, "NIFTY FUT"),
        row(far, "NIFTY", _FAR, "NIFTY FUT"),
        row(expired, "NIFTY", _EXPIRED, "NIFTY FUT"),
        row(bank_near, "BANKNIFTY", _NEAR, "BANKNIFTY FUT"),
        # A call option must never enter the futures universe.
        row(f"NSE:NIFTY{_NEAR:%y%b}25000CE".upper(), "NIFTY", _NEAR, "NIFTY 25000 CE"),
    ]


def _master_csv() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for cells in _master_rows():
        writer.writerow(cells)
    return buffer.getvalue()


# ------------------------------------------------------------------- history


def test_history_fetch_returns_normalized_candles():
    client = FakeFyersClient(_rows(3))
    service = PatternHistoryService(client, default_resolution="60", lookback_days=10)
    frame = service.fetch(
        _instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3)
    )
    assert list(frame.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert len(frame) == 3
    assert str(frame["timestamp"].dt.tz) == TZ
    assert client.calls[0]["resolution"] == "60"
    assert client.calls[0]["date_format"] == "0"
    assert client.calls[0]["cont_flag"] == "0"


def test_history_fetch_chunks_long_ranges_and_uses_epoch_bounds():
    client = FakeFyersClient([])
    service = PatternHistoryService(
        client, default_resolution="60", lookback_days=10, chunk_days=4
    )
    with pytest.raises(NoMarketDataError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 10))

    assert len(client.calls) == 3  # 10 days in 4-day chunks
    starts = [int(call["range_from"]) for call in client.calls]
    ends = [int(call["range_to"]) for call in client.calls]
    assert starts == sorted(starts)
    assert ends == sorted(ends)
    # Chunks are contiguous, with a single day of overlap avoided by design.
    assert ends[0] == starts[0] + 3 * 86400
    assert starts[1] == ends[0] + 86400


def test_history_fetch_merges_a_single_day_tail_chunk():
    """A 1-day remainder becomes a zero-width FYERS range, so merge it."""
    client = FakeFyersClient([])
    service = PatternHistoryService(
        client, default_resolution="60", lookback_days=120, chunk_days=60
    )
    with pytest.raises(NoMarketDataError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 10))

    assert len(client.calls) == 2
    starts = [int(call["range_from"]) for call in client.calls]
    ends = [int(call["range_to"]) for call in client.calls]
    assert all(start < end for start, end in zip(starts, ends))
    assert ends[-1] == int(_epoch(date(2024, 11, 10)))
    assert starts[1] == ends[0] + 86400


def test_history_paces_successive_requests(monkeypatch):
    from app.scanner.patterns import history as history_module

    clock = _FakeClock()
    monkeypatch.setattr(history_module, "time", clock)

    client = FakeFyersClient([])
    service = PatternHistoryService(
        client,
        lookback_days=10,
        chunk_days=4,
        max_retries=0,
        request_pause_seconds=0.5,
    )
    with pytest.raises(NoMarketDataError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 10))

    assert len(client.calls) == 3
    assert clock.sleeps == pytest.approx([0.5, 0.5])


def test_history_backs_off_for_a_minute_on_rate_limit(monkeypatch):
    from app.scanner.patterns import history as history_module

    clock = _FakeClock()
    monkeypatch.setattr(history_module, "time", clock)

    client = FakeFyersClient(
        _rows(2),
        errors=[
            FyersError(
                "You've reached the Standard plan limit of 50 requests/minute"
            )
        ],
    )
    service = PatternHistoryService(
        client,
        lookback_days=2,
        chunk_days=5,
        max_retries=1,
        request_pause_seconds=0,
        retry_pause_seconds=0,
        rate_limit_pause_seconds=60,
    )
    frame = service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3))

    assert len(frame) == 2
    assert len(client.calls) == 2
    assert clock.sleeps == pytest.approx([60.0])


def test_history_fetch_clips_candles_after_end_date():
    rows = [
        [EPOCH, 100.0, 101.0, 99.0, 100.5, 10.0],
        [EPOCH + 86400, 100.0, 101.0, 99.0, 100.5, 10.0],
    ]
    client = FakeFyersClient(rows)
    service = PatternHistoryService(client, lookback_days=10, chunk_days=30)
    frame = service.fetch(
        _instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3)
    )
    assert len(frame) == 1


def test_history_without_candles_raises_no_market_data():
    service = PatternHistoryService(FakeFyersClient([]), lookback_days=5)
    with pytest.raises(NoMarketDataError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3))


def test_history_retries_transient_failure_once():
    client = FakeFyersClient(
        _rows(2), errors=[FyersError("FYERS request failed with status 500")]
    )
    service = PatternHistoryService(
        client, lookback_days=2, chunk_days=5, max_retries=1, retry_pause_seconds=0
    )
    frame = service.fetch(
        _instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3)
    )
    assert len(frame) == 2
    assert len(client.calls) == 2


def test_history_does_not_retry_auth_failures():
    client = FakeFyersClient(
        _rows(2), error=FyersError("FYERS access token expired or was rejected")
    )
    service = PatternHistoryService(
        client, lookback_days=2, chunk_days=5, max_retries=2, retry_pause_seconds=0
    )
    with pytest.raises(FyersError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3))
    assert len(client.calls) == 1


def test_history_rejects_unknown_resolution_before_requesting():
    client = FakeFyersClient(_rows(2))
    service = PatternHistoryService(client, lookback_days=2)
    with pytest.raises(ValueError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), resolution="weekly")
    assert client.calls == []


def test_history_raises_on_malformed_candles_object():
    class Malformed(FakeFyersClient):
        def history(self, symbol, **kwargs):
            return {"s": "ok", "candles": {"unexpected": True}}

    service = PatternHistoryService(Malformed(), lookback_days=2)
    with pytest.raises(FyersError):
        service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3))


def test_history_uses_iso_dates_when_date_format_is_one():
    client = FakeFyersClient(_rows(1))
    service = PatternHistoryService(client, lookback_days=2, date_format="1")
    service.fetch(_instrument("NSE:TEST26NOVFUT"), end_date=date(2024, 11, 3))
    assert client.calls[0]["range_from"] == "2024-11-01"
    assert client.calls[0]["range_to"] == "2024-11-03"


# ---------------------------------------------------------- insufficient data


def test_insufficient_candles_return_no_pattern_not_an_error():
    """Fewer completed candles than ``min_candles`` must not raise."""
    frame = add_indicators(make_frame(pattern_count=1, baseline_count=1))
    assert len(frame) == 2
    assert PatternDetector(PatternConfig(min_candles=6, max_candles=6)).detect(frame) is None


def test_detector_returns_none_without_any_candle():
    assert PatternDetector().detect(pd.DataFrame()) is None


# -------------------------------------------------------- instrument master


def test_parse_instrument_master_keeps_only_valid_futures():
    frame = parse_instrument_master(_master_csv())
    assert set(frame["symbol"]) == {
        _symbol("NIFTY", "near"),
        _symbol("NIFTY", "far"),
        _symbol("NIFTY", "expired"),
        _symbol("BANKNIFTY", "near"),
    }
    assert frame.loc[frame["underlying"] == "NIFTY", "is_index"].all()
    assert frame.loc[frame["underlying"] == "BANKNIFTY", "is_index"].all()
    assert frame["lot_size"].dropna().eq(50.0).all()


def test_parse_instrument_master_accepts_a_header_row():
    text = (
        "symbol,description,underlying,expiry,lot_size,tick_size,fy_token\n"
        f"{_symbol('NIFTY', 'near')},NIFTY FUT,NIFTY,"
        f"{_epoch(date.today() + timedelta(days=5))},50,0.05,123\n"
    )
    frame = parse_instrument_master(text)
    assert len(frame) == 1
    assert frame["symbol"].iloc[0] == _symbol("NIFTY", "near")


def test_parse_instrument_master_rejects_empty_input():
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master("")
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master("   \n  ")


def test_parse_instrument_master_rejects_a_master_without_futures():
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    cells = [""] * 14
    cells[1] = "NIFTY 25000 CE"
    cells[8] = _epoch(date.today() + timedelta(days=5))
    cells[9] = "NSE:NIFTY25NOV25000CE"
    cells[13] = "NIFTY"
    writer.writerow(cells)
    with pytest.raises(InstrumentMasterError):
        parse_instrument_master(buffer.getvalue())


def test_select_active_futures_filters_expired_and_current_expiry():
    master = parse_instrument_master(_master_csv())
    active = select_active_futures(master)
    assert _symbol("NIFTY", "expired") not in set(active["symbol"])

    current = select_active_futures(master, current_expiry_only=True)
    assert _symbol("NIFTY", "far") not in set(current["symbol"])
    assert _symbol("NIFTY", "near") in set(current["symbol"])


def test_select_active_futures_can_exclude_index_contracts():
    master = parse_instrument_master(_master_csv())
    only_stock = select_active_futures(master, include_index=False)
    assert only_stock.empty


def test_to_instruments_round_trips_master_rows():
    master = parse_instrument_master(_master_csv())
    instruments = to_instruments(select_active_futures(master))
    assert instruments
    first = instruments[0]
    assert first.symbol.startswith("NSE:")
    assert first.underlying
    assert isinstance(first.expiry, date)
    assert first.lot_size == 50.0


# ------------------------------------------------------ symbol resolution


def test_resolve_instrument_accepts_a_full_fyers_symbol():
    instrument = resolve_instrument("nse:nifty25novfut")
    assert instrument.symbol == "NSE:NIFTY25NOVFUT"
    assert instrument.underlying == "NIFTY"
    assert instrument.expiry is None


def test_resolve_instrument_maps_an_underlying_to_nearest_expiry():
    master = parse_instrument_master(_master_csv())
    instrument = resolve_instrument("NIFTY", master)
    assert instrument.symbol == _symbol("NIFTY", "near")
    assert instrument.expiry is not None


def test_resolve_instrument_prefers_an_exact_symbol_match():
    master = parse_instrument_master(_master_csv())
    instrument = resolve_instrument(_symbol("NIFTY", "far"), master)
    assert instrument.symbol == _symbol("NIFTY", "far")


def test_resolve_instrument_rejects_unknown_bare_symbol():
    with pytest.raises(ValueError):
        resolve_instrument("NOTASYMBOL")
    with pytest.raises(ValueError):
        resolve_instrument("")


# ---------------------------------------------------- instrument master provider


def test_instrument_master_provider_uses_the_injected_fetcher_and_caches():
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        return _master_csv()

    provider = InstrumentMasterProvider(
        "https://example.invalid/NSE_FO.csv", fetcher=fetcher
    )
    first = provider.load()
    second = provider.load()
    assert len(calls) == 1
    assert not first.empty
    assert len(second) == len(first)

    forced = provider.load(force=True)
    assert len(calls) == 2
    assert len(forced) == len(first)


def test_instrument_master_provider_rejects_unexpected_payload():
    provider = InstrumentMasterProvider(
        "https://example.invalid/NSE_FO.csv", fetcher=lambda url: "<html>oops</html>"
    )
    with pytest.raises(InstrumentMasterError):
        provider.load()


def test_instrument_master_provider_instruments_only_current_expiry():
    provider = InstrumentMasterProvider(
        "https://example.invalid/NSE_FO.csv", fetcher=lambda url: _master_csv()
    )
    instruments = provider.instruments(current_expiry_only=True)
    symbols = {instrument.symbol for instrument in instruments}
    assert _symbol("NIFTY", "near") in symbols
    assert _symbol("NIFTY", "far") not in symbols


# ---------------------------------------------------------------- helpers


def _instrument(symbol: str):
    from .pattern_fixtures import make_instrument

    return make_instrument(symbol, expiry=None)


def _epoch(value: date) -> str:
    return str(int(pd.Timestamp(value).tz_localize(TZ).timestamp()))
