"""FYERS option-chain to scanner-row conversion (no network)."""
from __future__ import annotations

from app.services.kotak_scan_service import _parse_fyers_chain
from app.services.oi_scan_builder import build_candidate_row, build_headers, rows_to_csv

STRIKES = [24700, 24750, 24800, 24850, 24900, 24950, 25000, 25050,
           25100, 25150, 25200, 25250, 25300, 25350, 25400]
ATM = 25050


def _row(strike: int, option_type: str, oi: int, oich: int, *, include_oich: bool = True) -> dict:
    item = {
        "symbol": f"NSE:NIFTY25NOV{strike}{option_type}",
        "option_type": option_type,
        "strike_price": str(strike),
        "oi": str(oi),
        "ltp": "100",
    }
    if include_oich:
        item["oich"] = str(oich)
    else:
        item["previous_oi"] = str(oi - oich)
    return item


def _response(*, include_oich: bool = True) -> dict:
    rows = []
    for strike in STRIKES:
        rows.append(_row(strike, "CE", 100000, strike - 24000, include_oich=include_oich))
        rows.append(_row(strike, "PE", 100000, 26000 - strike, include_oich=include_oich))
    return {"s": "ok", "data": {"optionsChain": rows}}


def test_fyers_uses_oich_and_buckets():
    calls, puts = _parse_fyers_chain(_response())
    row = build_candidate_row("NIFTY", 25044.65, calls, puts, depth=5)
    assert row is not None
    assert row["ATM_Strike"] == ATM
    assert row["ATM_CallOI"] == ATM - 24000
    assert row["ATM_PutOI"] == 26000 - ATM
    assert row["CE_ITM1_Strike"] == 25000
    assert row["CE_OTM1_Strike"] == 25100
    assert row["PE_ITM1_Strike"] == 25100
    assert row["PE_OTM1_Strike"] == 25000


def test_fyers_falls_back_to_previous_oi():
    calls, puts = _parse_fyers_chain(_response(include_oich=False))
    assert calls[ATM]["oi_change"] == ATM - 24000
    assert puts[ATM]["oi_change"] == 26000 - ATM


def test_fyers_csv_matches_extension_header():
    calls, puts = _parse_fyers_chain(_response())
    row = build_candidate_row("NIFTY", 25044.65, calls, puts, depth=5)
    assert row is not None
    header, first = rows_to_csv([row], 5).decode("utf-8").splitlines()[:2]
    assert header == ",".join(build_headers(5))
    assert first.startswith("NIFTY,25044.65,1.0,25050,1050,950")
