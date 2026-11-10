"""Kotak client mapping and quote parsing without network access."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.market_data.kotak_client import (
    KotakClient,
    KotakError,
    KotakScripMaster,
    base_symbol,
)

CSV = """pSymbol,pExchSeg,pTrdSymbol,pSymbolName,pGroup
1333,nse_cm,HDFCBANK-EQ,HDFCBANK,EQ
2885,nse_cm,RELIANCE-EQ,RELIANCE,EQ
12900,nse_cm,YESBANK-BL,YESBANK,BL
"""


class FakeSDK:
    def __init__(self, rows):
        self.rows = rows
        self.quote_calls = []

    def scrip_master(self, exchange_segment=None):  # pragma: no cover - cache is fresh
        raise AssertionError("scrip master must not be downloaded when the cache is fresh")

    def quotes(self, instrument_tokens, quote_type="ltp"):
        self.quote_calls.append((list(instrument_tokens), quote_type))
        return list(self.rows)


def _client(tmp_path: Path, rows) -> tuple[KotakClient, FakeSDK]:
    cache = tmp_path / "kotak_scrip.csv"
    cache.write_text(CSV, encoding="utf-8")
    sdk = FakeSDK(rows)
    client = KotakClient(
        sdk_factory=lambda: sdk,
        master=KotakScripMaster(path=str(cache)),
        consumer_key="consumer-key",
    )
    return client, sdk


def test_base_symbol_strips_only_trading_suffixes():
    assert base_symbol("WIPRO-EQ") == "WIPRO"
    assert base_symbol("M&M-EQ") == "M&M"
    assert base_symbol("Nifty 50") == "NIFTY 50"


def test_ltp_map_resolves_equities_and_indices(tmp_path):
    rows = [
        {"exchange_token": "1333", "ltp": "801.6000"},
        {"exchange_token": "2885", "ltp": "2900.5"},
        {"exchange_token": "Nifty 50", "ltp": "25044.65"},
    ]
    client, sdk = _client(tmp_path, rows)

    prices = client.ltp_map(["hdfcbank", "RELIANCE", "NIFTY", "UNKNOWN"])

    assert prices == {"HDFCBANK": 801.6, "RELIANCE": 2900.5, "NIFTY": 25044.65}
    payload, quote_type = sdk.quote_calls[0]
    assert quote_type == "ltp"
    assert {"instrument_token": "1333", "exchange_segment": "nse_cm"} in payload
    assert {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"} in payload


def test_ltp_map_skips_missing_ltp(tmp_path):
    client, _ = _client(tmp_path, [{"exchange_token": "1333", "ltp": ""}])
    assert client.ltp_map(["HDFCBANK"]) == {}


def test_scrip_master_prefers_eq_listing(tmp_path):
    cache = tmp_path / "kotak_scrip.csv"
    cache.write_text(CSV, encoding="utf-8")
    master = KotakScripMaster(path=str(cache))
    master.ensure_loaded(FakeSDK([]))

    assert master.token_for("YESBANK") == ("nse_cm", "12900")
    assert master.token_for("WIPRO") is None
    assert master.symbol_for_trading_symbol("HDFCBANK-EQ") == "HDFCBANK"


def test_auth_error_response_raises():
    with pytest.raises(KotakError):
        KotakClient._raise_on_error(
            {"status": "error", "message": "Invalid MPIN."}, "MPIN validation"
        )
