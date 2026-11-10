"""Build scanner CSVs from Kotak or FYERS option-chain data.

Both providers normalize to the same scanner columns. The filter itself still
runs server-side through ``scan_service.handle_csv_upload``.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, time as time_of_day

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutils import IST
from app.db.session import get_sessionmaker
from app.market_data.fyers_client import FyersClient, FyersError
from app.market_data.kotak_client import KotakClient, KotakError, normalize_symbol
from app.services import scan_service
from app.services.oi_scan_builder import (
    build_candidate_row as _build_row,
    build_headers,
    rows_to_csv,
)

logger = get_logger(__name__)

MAX_SYMBOLS = 250
REQUEST_PAUSE_SECONDS = 0.05

__all__ = ["build_candidate_row", "build_headers", "rows_to_csv", "solve_symbols", "run_scan_job"]


def _moneyness(value) -> str:
    return str(value or "").strip().lower()


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- Kotak


def _kotak_entry(item: dict) -> dict | None:
    instrument = item.get("instrument") or item.get("inst") or {}
    quote = item.get("quote") or {}
    oi = item.get("openInterest") or item.get("oi") or {}
    strike = _number(instrument.get("strikePrice") or instrument.get("strkPrc"))
    if strike is None:
        return None
    option_type = str(
        instrument.get("optionType") or instrument.get("optType") or ""
    ).upper()
    current = _number(oi.get("current", oi.get("cur")))
    previous = _number(oi.get("previous", oi.get("prev")))
    if current is None or previous is None:
        return None
    return {
        "strike": strike,
        "type": option_type,
        "moneyness": _moneyness(instrument.get("moneyness")),
        "oi": current,
        # Kotak's oi.chg/chgPct are the option's price change, not OI change.
        "oi_change": current - previous,
        "ltp": _number(quote.get("ltp")),
    }


def _kotak_payload(response) -> dict:
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


def _parse_kotak_chain(response) -> tuple[dict[float, dict], dict[float, dict]]:
    data = _kotak_payload(response)
    calls: dict[float, dict] = {}
    puts: dict[float, dict] = {}
    for item in data.get("call") or []:
        entry = _kotak_entry(item)
        if entry and entry["type"] in {"", "CE"}:
            calls[entry["strike"]] = entry
    for item in data.get("put") or []:
        entry = _kotak_entry(item)
        if entry and entry["type"] in {"", "PE"}:
            puts[entry["strike"]] = entry
    return calls, puts


# --------------------------------------------------------------------------- FYERS


def _parse_fyers_chain(response) -> tuple[dict[float, dict], dict[float, dict]]:
    if not isinstance(response, dict) or response.get("s") != "ok":
        message = response.get("message") if isinstance(response, dict) else None
        raise FyersError(message or "FYERS option chain request failed")
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    rows = (
        data.get("optionsChain")
        or data.get("options_chain")
        or data.get("optionschain")
        or []
    )
    calls: dict[float, dict] = {}
    puts: dict[float, dict] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        option_type = str(
            item.get("option_type") or item.get("optionType") or ""
        ).upper()
        strike = _number(
            item.get("strike_price") or item.get("strikePrice") or item.get("strike")
        )
        if strike is None or option_type not in {"CE", "PE"}:
            continue
        oi = _number(item.get("oi") or item.get("open_interest") or item.get("openInterest")) or 0.0
        change = _number(
            item.get("oich")
            or item.get("oi_change")
            or item.get("oiChange")
            or item.get("change_in_oi")
        )
        if change is None:
            previous = _number(
                item.get("previous_oi")
                or item.get("prev_oi")
                or item.get("previousOpenInterest")
            )
            change = oi - previous if previous is not None else 0.0
        entry = {
            "strike": strike,
            "type": option_type,
            "moneyness": _moneyness(item.get("moneyness")),
            "oi": oi,
            # FYERS exposes the day's OI change directly as ``oich``.
            "oi_change": change,
            "ltp": _number(item.get("ltp")),
        }
        (calls if option_type == "CE" else puts)[strike] = entry
    return calls, puts


def build_candidate_row(symbol: str, spot: float, chain: dict, depth: int = 5) -> dict | None:
    """Backward-compatible Kotak chain wrapper used by the tests."""
    calls, puts = _parse_kotak_chain(chain)
    return _build_row(symbol, float(spot), calls, puts, depth)


# --------------------------------------------------------------------------- runner


def _fyers_timestamp(expiry: str | None) -> str | int:
    if not expiry:
        return ""
    try:
        day = date.fromisoformat(expiry)
    except ValueError:
        return expiry
    close = datetime.combine(day, time_of_day(15, 30), tzinfo=IST)
    return int(close.timestamp())


def _fyers_symbol(symbol: str) -> str:
    from app.workers.price_tracker_worker import to_fyers_symbol

    return to_fyers_symbol(symbol)


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


def _provider(name: str | None) -> str:
    selected = (name or get_settings().scanner_data_provider or "fyers").lower()
    return selected if selected in {"fyers", "kotak"} else "fyers"


def run_scan_job(
    scan_id: uuid.UUID,
    symbols: list[str],
    depth: int,
    expiry: str | None,
    provider: str | None = None,
) -> None:
    """Background job: fetch option-chain OI data and run the existing scanner."""
    source = _provider(provider)
    session = get_sessionmaker()()
    client = None
    try:
        scan = scan_service.get_scan(session, scan_id)
        scan.status = "RUNNING"
        session.commit()

        if source == "kotak":
            kotak = KotakClient()
            if not kotak.configured:
                raise KotakError("Kotak consumer key is not configured")
            spots = kotak.ltp_map(symbols)
            fetch_chain = lambda symbol: kotak.sdk().option_chain(
                exchange="nse_fo",
                underlying=symbol,
                expiry=expiry or None,
                instrument_type="option",
                count=max(depth * 4, 40),
            )
            parse_chain = _parse_kotak_chain
            client = kotak
        else:
            fyers = FyersClient()
            if not fyers.configured:
                raise FyersError(
                    "FYERS is not configured; connect FYERS in admin settings or set FYERS_ACCESS_TOKEN"
                )
            fyers_symbols = {symbol: _fyers_symbol(symbol) for symbol in symbols}
            raw_spots = fyers.ltp_map(list(fyers_symbols.values()))
            spots = {
                symbol: raw_spots.get(fyers_symbol)
                for symbol, fyers_symbol in fyers_symbols.items()
            }
            timestamp = _fyers_timestamp(expiry)
            fetch_chain = lambda symbol: fyers.option_chain(
                fyers_symbols[symbol],
                strikecount=max(depth, 5),
                timestamp=timestamp,
            )
            parse_chain = _parse_fyers_chain
            client = fyers

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
                warnings.append(f"{symbol}: no underlying quote")
                continue
            try:
                calls, puts = parse_chain(fetch_chain(symbol))
                row = _build_row(symbol, float(spot), calls, puts, depth)
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
                error_message="; ".join(warnings[:20]) or "No option-chain rows",
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
        logger.exception(
            "oi_scan_failed", extra={"scan_id": str(scan_id), "provider": source}
        )
        try:
            scan = scan_service.get_scan(session, scan_id)
            scan_service.complete_scan(
                session, scan, status="FAILED", error_message=str(exc)[:4000]
            )
        except Exception:  # noqa: BLE001
            session.rollback()
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        session.close()
