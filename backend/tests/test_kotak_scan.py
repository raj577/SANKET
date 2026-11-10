"""Kotak option-chain to scanner CSV conversion (no network)."""
from __future__ import annotations

from app.services.kotak_scan_service import (
    build_candidate_row,
    build_headers,
    rows_to_csv,
)

STRIKES = [24700, 24750, 24800, 24850, 24900, 24950, 25000, 25050,
           25100, 25150, 25200, 25250, 25300, 25350, 25400]
ATM = 25050


def _leg(strike: int, option_type: str, delta: int, *, full: bool = False) -> dict:
    instrument = {
        "strikePrice": str(strike),
        "optionType": option_type,
        "moneyness": "ATM" if strike == ATM else ("ITM" if strike < ATM else "OTM"),
    }
    oi = {
        "current": 100000 + delta,
        "previous": 100000,
        # Deliberately wrong for OI change: this is the option's price change.
        "change": -37,
        "changePct": -13.7,
    }
    if not full:
        return {
            "inst": {"strkPrc": str(strike), "optType": option_type, "moneyness": instrument["moneyness"]},
            "oi": {"cur": str(oi["current"]), "prev": str(oi["previous"]), "chg": "-37", "chgPct": "-13.7"},
        }
    return {
        "instrument": instrument,
        "openInterest": oi,
        "quote": {"ltp": "100"},
    }


def _chain(full: bool = False) -> dict:
    return {
        "call": [_leg(strike, "CE", strike - 24000, full=full) for strike in STRIKES],
        "put": [_leg(strike, "PE", 26000 - strike, full=full) for strike in STRIKES],
    }


def test_build_row_uses_oi_delta_and_strike_buckets():
    row = build_candidate_row("NIFTY", 25044.65, _chain(), depth=5)
    assert row is not None
    assert row["ATM_Strike"] == ATM
    assert row["ATM_CallOI"] == ATM - 24000
    assert row["ATM_PutOI"] == 26000 - ATM
    # Calls below ATM are ITM, nearest first.
    assert row["CE_ITM1_Strike"] == 25000
    assert row["CE_ITM2_Strike"] == 24950
    assert row["CE_ITM1_CallOI"] == 25000 - 24000
    assert row["CE_OTM1_Strike"] == 25100
    # Puts above ATM are ITM, nearest first.
    assert row["PE_ITM1_Strike"] == 25100
    assert row["PE_OTM1_Strike"] == 25000
    assert row["PE_OTM1_PutOI"] == 26000 - 25000
    assert row["PCR"] == 1.0


def test_full_api_shape_is_supported():
    row = build_candidate_row("NIFTY", 25044.65, _chain(full=True), depth=5)
    assert row is not None
    assert row["ATM_CallOI"] == ATM - 24000


def test_csv_header_matches_extension_columns():
    row = build_candidate_row("NIFTY", 25044.65, _chain(), depth=5)
    assert row is not None
    payload = rows_to_csv([row], 5).decode("utf-8")
    header, first = payload.splitlines()[:2]
    assert header == ",".join(build_headers(5))
    assert header.startswith("Symbol,Spot,PCR,ATM_Strike,ATM_CallOI,ATM_PutOI")
    assert first.startswith("NIFTY,25044.65,1.0,25050,1050,950")


def test_missing_depth_returns_none():
    chain = {"call": _chain()["call"][:6], "put": _chain()["put"][:6]}
    assert build_candidate_row("NIFTY", 25044.65, chain, depth=5) is None
