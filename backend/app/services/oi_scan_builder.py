"""Shared scanner-row builder for option-chain OI data.

Both the Kotak and FYERS providers normalize their payloads into
``{strike: {oi, oi_change, moneyness}}`` call/put maps and reuse this module so
the CSV columns and filter inputs stay identical to the extension.
"""
from __future__ import annotations

import csv
import io


def _nearest(strikes: list[float], reference: float) -> float | None:
    return min(strikes, key=lambda value: abs(value - reference)) if strikes else None


def _cell(value: float) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number


def bucket(
    side: dict[float, dict], atm: float, depth: int, *, calls: bool
) -> tuple[dict[int, dict], dict[int, dict]]:
    strikes = sorted(side)
    if calls:
        itm_strikes = [strike for strike in reversed(strikes) if strike < atm][:depth]
        otm_strikes = [strike for strike in strikes if strike > atm][:depth]
    else:
        itm_strikes = [strike for strike in strikes if strike > atm][:depth]
        otm_strikes = [strike for strike in reversed(strikes) if strike < atm][:depth]
    itm = {index + 1: side[strike] for index, strike in enumerate(itm_strikes)}
    otm = {index + 1: side[strike] for index, strike in enumerate(otm_strikes)}
    return itm, otm


def build_candidate_row(
    symbol: str,
    spot: float,
    calls: dict[float, dict],
    puts: dict[float, dict],
    depth: int = 5,
) -> dict | None:
    if not calls or not puts:
        return None

    atm_rows = [entry for entry in calls.values() if entry.get("moneyness") == "atm"]
    atm = atm_rows[0]["strike"] if atm_rows else _nearest(sorted(calls), spot)
    if atm is None or atm not in calls or atm not in puts:
        return None

    ce_itm, ce_otm = bucket(calls, atm, depth, calls=True)
    pe_itm, pe_otm = bucket(puts, atm, depth, calls=False)
    if any(len(item) < depth for item in (ce_itm, ce_otm, pe_itm, pe_otm)):
        return None

    total_call = sum(entry["oi"] for entry in calls.values())
    total_put = sum(entry["oi"] for entry in puts.values())
    pcr = round(total_put / total_call, 2) if total_call else ""

    row: dict[str, object] = {
        "Symbol": symbol,
        "Spot": spot,
        "PCR": pcr,
        "ATM_Strike": _cell(atm),
        "ATM_CallOI": _cell(calls[atm]["oi_change"]),
        "ATM_PutOI": _cell(puts[atm]["oi_change"]),
    }
    for index, entry in ce_itm.items():
        row[f"CE_ITM{index}_Strike"] = _cell(entry["strike"])
        row[f"CE_ITM{index}_CallOI"] = _cell(entry["oi_change"])
    for index, entry in ce_otm.items():
        row[f"CE_OTM{index}_Strike"] = _cell(entry["strike"])
        row[f"CE_OTM{index}_CallOI"] = _cell(entry["oi_change"])
    for index, entry in pe_itm.items():
        row[f"PE_ITM{index}_Strike"] = _cell(entry["strike"])
        row[f"PE_ITM{index}_PutOI"] = _cell(entry["oi_change"])
    for index, entry in pe_otm.items():
        row[f"PE_OTM{index}_Strike"] = _cell(entry["strike"])
        row[f"PE_OTM{index}_PutOI"] = _cell(entry["oi_change"])

    row["ITM_PE_Total"] = _cell(sum(pe_itm[i]["oi_change"] for i in pe_itm))
    row["OTM_PE_Total"] = _cell(sum(pe_otm[i]["oi_change"] for i in pe_otm))
    row["ITM_CE_Total"] = _cell(sum(ce_itm[i]["oi_change"] for i in ce_itm))
    row["OTM_CE_Total"] = _cell(sum(ce_otm[i]["oi_change"] for i in ce_otm))
    return row


def build_headers(depth: int) -> list[str]:
    headers = ["Symbol", "Spot", "PCR", "ATM_Strike", "ATM_CallOI", "ATM_PutOI"]
    for index in range(1, depth + 1):
        headers.extend([f"CE_ITM{index}_Strike", f"CE_ITM{index}_CallOI"])
    for index in range(1, depth + 1):
        headers.extend([f"CE_OTM{index}_Strike", f"CE_OTM{index}_CallOI"])
    for index in range(1, depth + 1):
        headers.extend([f"PE_ITM{index}_Strike", f"PE_ITM{index}_PutOI"])
    for index in range(1, depth + 1):
        headers.extend([f"PE_OTM{index}_Strike", f"PE_OTM{index}_PutOI"])
    headers.extend(
        [
            "ITM_PE_Total",
            "ITM_CE_Total",
            "OTM_PE_Total",
            "OTM_CE_Total",
            "SupportMigration",
            "ResistanceMigration",
        ]
    )
    return headers


def rows_to_csv(rows: list[dict], depth: int) -> bytes:
    headers = build_headers(depth)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
