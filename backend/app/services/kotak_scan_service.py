"""Build scanner CSVs from Kotak option-chain data.

The scanner consumes signed OI *changes*. Kotak's option-chain payload exposes
``oi.current`` and ``oi.previous``; the ``oi.chg``/``chgPct`` fields are the
option's price change (verified against ``quote.ltp - quote.prevClose``), not
OI change, so they must not be used here.

Requires only the Kotak consumer key; no TOTP/MPIN session is needed.
"""
from __future__ import annotations

import csv
import io
import time
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.market_data.kotak_client import KotakClient, KotakError, normalize_symbol
from app.services import scan_service

logger = get_logger(__name__)

MAX_SYMBOLS = 250
REQUEST_PAUSE_SECONDS = 0.05


def _moneyness(value) -> str:
    return str(value or "").strip().lower()


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _entry(item: dict) -> dict | None:
    instrument = item.get("instrument") or item.get("inst") or {}
    quote = item.get("quote") or {}
    oi = item.get("openInterest") or item.get("oi") or {}
    strike = _number(instrument.get("strikePrice") or instrument.get("strkPrc"))
    if strike is None:
        return None
    option_type = str(
        instrument.get("optionType") or instrument.get("optType") or ""
    ).upper()
    current = oi.get("current", oi.get("cur"))
    previous = oi.get("previous", oi.get("prev"))
    current_value = _number(current)
    previous_value = _number(previous)
    if current_value is None or previous_value is None:
        return None
    return {
        "strike": strike,
        "type": option_type,
        "moneyness": _moneyness(instrument.get("moneyness")),
        "oi": current_value,
        "oi_change": current_value - previous_value,
        "ltp": _number(quote.get("ltp")),
    }


def _chain_payload(response) -> dict:
    if not isinstance(response, dict):
        raise KotakError("Kotak option chain returned an unexpected response")
    if str(response.get("stat") or "").lower() == "not_ok":
        raise KotakError(
            response.get("emsg") or response.get("message") or "option chain failed"
        )
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    if not isinstance(data.get("call"), list) and not isinstance(data.get("put"), list):
        raise KotakError("Kotak option chain returned no call/put rows")
    return data


def _nearest(strikes: list[float], reference: float) -> float | None:
    return min(strikes, key=lambda value: abs(value - reference)) if strikes else None


def _cell(value: float) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number


def _bucket(
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
    symbol: str, spot: float, chain: dict, depth: int = 5
) -> dict | None:
    """Convert one option-chain payload into the scanner's CSV column names."""
    calls: dict[float, dict] = {}
    puts: dict[float, dict] = {}
    for item in chain.get("call") or []:
        entry = _entry(item)
        if entry and entry["type"] in {"", "CE"}:
            calls[entry["strike"]] = entry
    for item in chain.get("put") or []:
        entry = _entry(item)
        if entry and entry["type"] in {"", "PE"}:
            puts[entry["strike"]] = entry
    if not calls or not puts:
        return None

    atm_rows = [entry for entry in calls.values() if entry["moneyness"] == "atm"]
    atm = atm_rows[0]["strike"] if atm_rows else _nearest(sorted(calls), spot)
    if atm is None or atm not in calls or atm not in puts:
        return None

    ce_itm, ce_otm = _bucket(calls, atm, depth, calls=True)
    pe_itm, pe_otm = _bucket(puts, atm, depth, calls=False)
    if any(len(bucket) < depth for bucket in (ce_itm, ce_otm, pe_itm, pe_otm)):
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


def solve_symbols(db: Session, symbols: list[str] | None) -> list[str]:
    if symbols:
        resolved = [normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)]
    else:
        from app.services import settings_service

        watchlist = settings_service.get_value(db, "watchlist")
        resolved = [
            normalize_symbol(symbol)
            for symbol in watchlist.get("symbols", [])
            if normalize_symbol(symbol)
        ]
    return list(dict.fromkeys(resolved))[:MAX_SYMBOLS]


def run_scan_job(
    scan_id: uuid.UUID,
    symbols: list[str],
    depth: int,
    expiry: str | None,
) -> None:
    """Background job: fetch Kotak option chains and run the existing scanner."""
    session = get_sessionmaker()()
    client = KotakClient()
    try:
        scan = scan_service.get_scan(session, scan_id)
        scan.status = "RUNNING"
        session.commit()

        spots = client.ltp_map(symbols)
        rows: list[dict] = []
        failed = 0
        warnings: list[str] = []

        for index, symbol in enumerate(symbols, start=1):
            scan_service.record_progress(
                session,
                scan,
                current_symbol=symbol,
                total_symbols=len(symbols),
                successful_symbols=index - 1 - failed,
                failed_symbols=failed,
            )
            spot = spots.get(symbol)
            if spot is None:
                failed += 1
                warnings.append(f"{symbol}: no equity quote")
                continue
            try:
                response = client.sdk().option_chain(
                    exchange="nse_fo",
                    underlying=symbol,
                    expiry=expiry or None,
                    instrument_type="option",
                    count=max(depth * 4, 40),
                )
                chain = _chain_payload(response)
                row = build_candidate_row(symbol, float(spot), chain, depth)
            except Exception as exc:  # noqa: BLE001 - one symbol must not stop the scan
                failed += 1
                warnings.append(f"{symbol}: {exc}")
                time.sleep(REQUEST_PAUSE_SECONDS)
                continue
            if row is None:
                failed += 1
                warnings.append(f"{symbol}: option chain missing required strikes")
            else:
                rows.append(row)
            time.sleep(REQUEST_PAUSE_SECONDS)

        if not rows:
            scan_service.complete_scan(
                session,
                scan,
                status="FAILED",
                successful_symbols=0,
                failed_symbols=failed,
                error_message="; ".join(warnings[:20]) or "No Kotak option-chain rows",
            )
            return

        scan_service.handle_csv_upload(
            session,
            scan,
            content=rows_to_csv(rows, depth),
            total_symbols=len(symbols),
            successful_symbols=len(rows),
            failed_symbols=failed,
        )
        if warnings:
            scan = scan_service.get_scan(session, scan_id)
            scan.error_message = "; ".join(warnings[:20])
            session.commit()
    except Exception as exc:  # noqa: BLE001 - never leave the scan stuck
        logger.exception("kotak_scan_failed", extra={"scan_id": str(scan_id)})
        try:
            scan = scan_service.get_scan(session, scan_id)
            scan_service.complete_scan(
                session, scan, status="FAILED", error_message=str(exc)[:4000]
            )
        except Exception:  # noqa: BLE001
            session.rollback()
    finally:
        session.close()
