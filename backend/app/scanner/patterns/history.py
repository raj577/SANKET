"""FYERS historical candles and NSE futures instruments for the pattern scanner.

This module reuses Project A's existing :class:`FyersClient` for the HTTP
transport and ports the normalization, chunking and instrument-master logic
from the original AVWAP scanner. It deliberately shares nothing with the OI
scanner except the FYERS client.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

import httpx
import pandas as pd

from app.market_data.errors import is_auth_error, is_rate_limit_error
from app.market_data.fyers_client import FyersClient, FyersError

from .candles import (
    NoMarketDataError,
    OHLCV_COLUMNS,
    normalize_candles,
    resolution_minutes,
)
from .models import Instrument

logger = logging.getLogger("sensibull.patterns.history")

DEFAULT_INDEX_UNDERLYINGS = (
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
)
DEFAULT_INSTRUMENT_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"

FUTURES_PATTERN = re.compile(r"^NSE:(?P<root>.+?)(?P<expiry>\d{2}[A-Z]{3})FUT$")
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# Known column positions in the headerless public NSE_FO master.
COL_FY_TOKEN = 0
COL_DESCRIPTION = 1
COL_LOT_SIZE = 2
COL_TICK_SIZE = 3
COL_EXPIRY_EPOCH = 8
COL_SYMBOL = 9
COL_UNDERLYING = 13

_HEADER_ALIASES = {
    "symbol": ("symbol", "ticker", "trading_symbol"),
    "description": ("description", "desc", "name"),
    "underlying": ("underlying", "underlying_symbol", "asset"),
    "expiry": ("expiry", "expiry_epoch", "expiry_date", "expiry_timestamp"),
    "lot_size": ("lot_size", "lotsize", "lot"),
    "tick_size": ("tick_size", "ticksize", "tick"),
    "fy_token": ("fy_token", "fytoken", "token"),
}


class InstrumentMasterError(RuntimeError):
    """Raised when the futures universe cannot be loaded or validated."""


# Kept as module-level aliases so existing call sites and tests stay valid.
_is_auth_error = is_auth_error
_is_rate_limit_error = is_rate_limit_error


class PatternHistoryService:
    """Chunked historical candle retrieval through Project A's FYERS client."""

    def __init__(
        self,
        client: FyersClient,
        *,
        default_resolution: str = "60",
        lookback_days: int = 120,
        chunk_days: int = 60,
        timezone: str = "Asia/Kolkata",
        date_format: str = "0",
        cont_flag: str = "0",
        max_retries: int = 1,
        retry_pause_seconds: float = 0.5,
        request_pause_seconds: float = 0.0,
        rate_limit_pause_seconds: float = 60.0,
    ) -> None:
        self.client = client
        self.default_resolution = str(default_resolution)
        self.lookback_days = max(int(lookback_days), 1)
        self.chunk_days = max(int(chunk_days), 1)
        self.timezone = timezone
        self.date_format = str(date_format)
        self.cont_flag = str(cont_flag)
        self.max_retries = max(int(max_retries), 0)
        self.retry_pause_seconds = max(float(retry_pause_seconds), 0.0)
        self.request_pause_seconds = max(float(request_pause_seconds), 0.0)
        self.rate_limit_pause_seconds = max(float(rate_limit_pause_seconds), 0.0)
        self._last_request_at: float | None = None

    def fetch(
        self,
        instrument: Instrument,
        resolution: str | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Return the contract's history from its first available candle.

        The lookback window is intentionally longer than an NSE futures
        contract's maximum tenure; the first returned candle is the AVWAP
        anchor.
        """

        resolution = str(resolution or self.default_resolution)
        resolution_minutes(resolution)  # validate early, before any request

        today = pd.Timestamp.now(tz=self.timezone).date()
        desired_end = min(end_date or today, instrument.expiry) if instrument.expiry else (end_date or today)
        desired_start = desired_end - timedelta(days=self.lookback_days)

        frame = self._fetch_range(
            instrument.symbol, resolution, desired_start, desired_end
        )
        frame = self._clip(frame, desired_end)
        if frame.empty:
            raise NoMarketDataError(
                f"No completed historical candles available for {instrument.symbol}."
            )
        logger.debug(
            "Fetched %s candles for %s (%s to %s)",
            len(frame),
            instrument.symbol,
            frame["timestamp"].min().date(),
            frame["timestamp"].max().date(),
        )
        return frame

    def _fetch_range(
        self,
        symbol: str,
        resolution: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        if start > end:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        rows: list[list[Any]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=self.chunk_days - 1), end)
            # A single-day tail becomes a zero-width range when the lookback is
            # an exact multiple of the chunk size, and FYERS rejects it. Fold it
            # into the preceding request instead.
            if 0 < (end - chunk_end).days <= 1:
                chunk_end = end
            rows.extend(
                self._request_chunk(
                    symbol=symbol,
                    resolution=resolution,
                    range_from=cursor,
                    range_to=chunk_end,
                )
            )
            cursor = chunk_end + timedelta(days=1)

        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        return normalize_candles(rows, self.timezone)

    def _wait_for_request_slot(self) -> None:
        """Space out FYERS history calls; bursty requests get HTTP 429."""
        if self.request_pause_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = self.request_pause_seconds - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _request_chunk(
        self,
        *,
        symbol: str,
        resolution: str,
        range_from: date,
        range_to: date,
    ) -> list[list[Any]]:
        last_error: FyersError | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_for_request_slot()
            try:
                payload = self.client.history(
                    symbol,
                    resolution=resolution,
                    range_from=self._range_value(range_from),
                    range_to=self._range_value(range_to),
                    date_format=self.date_format,
                    cont_flag=self.cont_flag,
                )
                candles = payload.get("candles") if isinstance(payload, dict) else None
                if candles is None:
                    return []
                if not isinstance(candles, list):
                    raise FyersError(
                        f"Malformed candles returned for {symbol}."
                    )
                return candles
            except FyersError as exc:
                last_error = exc
                if _is_auth_error(exc) or attempt >= self.max_retries:
                    raise
                limited = _is_rate_limit_error(exc)
                pause = (
                    self.rate_limit_pause_seconds
                    if limited
                    else self.retry_pause_seconds
                )
                logger.warning(
                    "History request failed for %s (attempt %s/%s, retrying in %.1fs): %s",
                    symbol,
                    attempt + 1,
                    self.max_retries + 1,
                    pause,
                    exc,
                )
                if pause:
                    time.sleep(pause)
        assert last_error is not None
        raise last_error

    def _range_value(self, value: date) -> str:
        if self.date_format == "1":
            return value.isoformat()
        stamp = pd.Timestamp(value.isoformat()).tz_localize(self.timezone)
        return str(int(stamp.timestamp()))

    @staticmethod
    def _clip(candles: pd.DataFrame, end_date: date) -> pd.DataFrame:
        if candles.empty:
            return candles.copy()
        timestamps = pd.to_datetime(candles["timestamp"])
        mask = timestamps.dt.date <= end_date
        return candles.loc[mask].reset_index(drop=True)


def _normalize_underlying(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _find_header_mapping(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized = [cell.strip().lower() for cell in header]
    for target, aliases in _HEADER_ALIASES.items():
        for index, cell in enumerate(normalized):
            if cell in aliases:
                mapping[target] = index
                break
    return mapping


def _parse_expiry(value: object, timezone: str) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None and numeric > 0:
        divisor = 1000.0 if numeric > 10_000_000_000 else 1.0
        try:
            stamp = pd.Timestamp(float(numeric) / divisor, unit="s", tz="UTC")
            return stamp.tz_convert(timezone).date()
        except (ValueError, OverflowError, OSError):
            return None
    try:
        stamp = pd.to_datetime(text, errors="coerce", dayfirst=True)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    try:
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(timezone)
        else:
            stamp = stamp.tz_convert(timezone)
        return stamp.date()
    except (ValueError, TypeError):
        return stamp.date()


def _valid_futures_symbol(symbol: str, underlying: str, description: str) -> bool:
    match = FUTURES_PATTERN.match(symbol)
    if not match:
        return False
    if "FUT" not in description.upper():
        return False
    if match.group("expiry")[-3:] not in MONTHS:
        return False
    # Verify the symbol prefix agrees with the master's underlying field.
    if _normalize_underlying(match.group("root")) != _normalize_underlying(underlying):
        return False
    return True


def parse_instrument_master(
    text: str,
    timezone: str = "Asia/Kolkata",
    index_underlyings: Iterable[str] = DEFAULT_INDEX_UNDERLYINGS,
) -> pd.DataFrame:
    """Parse the FYERS NSE_FO master into a validated futures DataFrame.

    Expired rows are retained here so callers can test/filter them explicitly;
    use :func:`select_active_futures` for the tradable universe.
    """

    if not text or not text.strip():
        raise InstrumentMasterError("Instrument master is empty.")

    reader = csv.reader(io.StringIO(text))
    try:
        first_row = next(reader)
    except StopIteration as exc:
        raise InstrumentMasterError("Instrument master has no rows.") from exc

    header_map = _find_header_mapping(first_row)
    has_header = "symbol" in header_map and "expiry" in header_map
    rows = reader if has_header else _chain_first(first_row, reader)

    index_set = {_normalize_underlying(item) for item in index_underlyings}
    records: list[dict[str, object]] = []
    rejected = 0

    for row in rows:
        if not row or all(not cell.strip() for cell in row):
            continue
        try:
            if has_header:
                symbol = row[header_map["symbol"]].strip()
                description = row[header_map.get("description", -1)].strip() if "description" in header_map else ""
                underlying = row[header_map["underlying"]].strip() if "underlying" in header_map else ""
                expiry_raw = row[header_map["expiry"]]
                lot_raw = row[header_map["lot_size"]] if "lot_size" in header_map else None
                tick_raw = row[header_map["tick_size"]] if "tick_size" in header_map else None
                token = row[header_map["fy_token"]] if "fy_token" in header_map else ""
            else:
                if len(row) <= COL_UNDERLYING:
                    rejected += 1
                    continue
                token = row[COL_FY_TOKEN].strip()
                description = row[COL_DESCRIPTION].strip()
                lot_raw = row[COL_LOT_SIZE]
                tick_raw = row[COL_TICK_SIZE]
                expiry_raw = row[COL_EXPIRY_EPOCH]
                symbol = row[COL_SYMBOL].strip()
                underlying = row[COL_UNDERLYING].strip()
        except IndexError:
            rejected += 1
            continue

        if not symbol.endswith("FUT"):
            continue
        if not _valid_futures_symbol(symbol, underlying, description):
            rejected += 1
            continue

        expiry = _parse_expiry(expiry_raw, timezone)
        if expiry is None:
            rejected += 1
            continue

        records.append(
            {
                "fy_token": token,
                "symbol": symbol,
                "description": description,
                "underlying": underlying,
                "expiry": expiry,
                "lot_size": _to_float(lot_raw),
                "tick_size": _to_float(tick_raw),
                "is_index": _normalize_underlying(underlying) in index_set,
            }
        )

    if not records:
        raise InstrumentMasterError(
            "No valid NSE futures contracts found in the instrument master."
        )

    frame = pd.DataFrame.from_records(records)
    frame = frame.drop_duplicates(subset=["symbol"], keep="first")
    frame = frame.sort_values(["underlying", "expiry", "symbol"]).reset_index(drop=True)
    frame["expiry"] = pd.to_datetime(frame["expiry"]).dt.date
    logger.info(
        "Parsed %s NSE futures contracts (%s rejected rows)",
        len(frame),
        rejected,
    )
    return frame


def _chain_first(first_row: list[str], remainder: Iterable[list[str]]) -> Iterable[list[str]]:
    yield first_row
    yield from remainder


def _to_float(value: object) -> float | None:
    try:
        number = float(str(value).strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def select_active_futures(
    master: pd.DataFrame,
    as_of: date | None = None,
    current_expiry_only: bool = False,
    include_index: bool = True,
) -> pd.DataFrame:
    """Return non-expired NSE futures, optionally only nearest expiry per underlying."""

    if master is None or master.empty:
        return master.copy() if master is not None else pd.DataFrame()
    if as_of is None:
        as_of = pd.Timestamp.now(tz="Asia/Kolkata").date()

    frame = master.copy()
    if "is_index" not in frame.columns:
        frame["is_index"] = False
    frame["expiry"] = pd.to_datetime(frame["expiry"]).dt.date
    frame = frame.loc[frame["expiry"] >= as_of].copy()
    if not include_index:
        frame = frame.loc[~frame["is_index"].astype(bool)].copy()
    if frame.empty:
        return frame

    frame["is_current_expiry"] = frame.groupby("underlying")["expiry"].transform("min") == frame["expiry"]
    if current_expiry_only:
        frame = frame.loc[frame["is_current_expiry"]].copy()
    return frame.sort_values(["underlying", "expiry", "symbol"]).reset_index(drop=True)


def to_instruments(frame: pd.DataFrame) -> list[Instrument]:
    instruments: list[Instrument] = []
    for row in frame.itertuples(index=False):
        instruments.append(
            Instrument(
                symbol=str(row.symbol),
                underlying=str(row.underlying),
                expiry=row.expiry,
                description=str(getattr(row, "description", "") or ""),
                lot_size=(
                    float(row.lot_size)
                    if getattr(row, "lot_size", None) is not None
                    and pd.notna(getattr(row, "lot_size"))
                    else None
                ),
                is_index=bool(getattr(row, "is_index", False)),
            )
        )
    return instruments


def _futures_root(symbol: str) -> str | None:
    match = FUTURES_PATTERN.match(symbol)
    return match.group("root") if match else None


def resolve_instrument(
    symbol: str,
    master: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> Instrument:
    """Resolve a user-supplied symbol.

    Full FYERS symbols (``NSE:...``) are accepted as-is. A bare underlying
    (``NIFTY``) is resolved to the nearest non-expired futures contract using
    the instrument master.
    """

    text = str(symbol or "").strip().upper()
    if not text:
        raise ValueError("Symbol is empty")

    if master is not None and not master.empty:
        symbols = master["symbol"].astype(str).str.upper()
        exact = master.loc[symbols == text]
        candidates = exact
        if candidates.empty:
            normalized = _normalize_underlying(
                text.split(":", 1)[1] if ":" in text else text
            )
            roots = master["underlying"].map(_normalize_underlying)
            candidates = master.loc[roots == normalized]
            if candidates.empty:
                root = _futures_root(text)
                if root:
                    candidates = master.loc[roots == _normalize_underlying(root)]
        if not candidates.empty:
            # Never resolve a bare underlying onto an expired contract; keep
            # expired rows only when nothing live is available so the caller
            # still gets a meaningful "contract expired" error.
            as_of = as_of or pd.Timestamp.now(tz="Asia/Kolkata").date()
            not_expired = candidates.loc[
                pd.to_datetime(candidates["expiry"]).dt.date >= as_of
            ]
            if not not_expired.empty:
                candidates = not_expired
            row = candidates.sort_values("expiry").iloc[0]
            return Instrument(
                symbol=str(row["symbol"]),
                underlying=str(row["underlying"]),
                expiry=row["expiry"],
                description=str(row.get("description", "") or ""),
                lot_size=(
                    float(row["lot_size"])
                    if row.get("lot_size") is not None and pd.notna(row.get("lot_size"))
                    else None
                ),
                is_index=bool(row.get("is_index", False)),
            )

    if ":" in text:
        return Instrument(
            symbol=text,
            underlying=_futures_root(text) or text.split(":", 1)[1],
        )
    raise ValueError(
        f"Unknown symbol {symbol!r}; use a full FYERS symbol "
        "(for example NSE:NIFTY25NOVFUT) or connect the instrument master."
    )


class InstrumentMasterProvider:
    """Downloads and parses the FYERS NSE_FO symbol master."""

    def __init__(
        self,
        url: str = DEFAULT_INSTRUMENT_MASTER_URL,
        *,
        timeout: float = 20.0,
        ttl_seconds: int = 3600,
        timezone: str = "Asia/Kolkata",
        index_underlyings: Iterable[str] = DEFAULT_INDEX_UNDERLYINGS,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.url = url
        self.timeout = float(timeout)
        self.ttl_seconds = max(int(ttl_seconds), 0)
        self.timezone = timezone
        self.index_underlyings = tuple(index_underlyings)
        self._fetcher = fetcher
        self._futures: pd.DataFrame | None = None
        self._loaded_at: float = 0.0

    def _download(self) -> str:
        if self._fetcher is not None:
            text = self._fetcher(self.url)
        else:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; sensibull-pattern-scanner/1.0; "
                    "+https://sensibull.com)"
                )
            }
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(self.url, headers=headers)
                response.raise_for_status()
                text = response.text
        if not text or "NSE:" not in text:
            raise InstrumentMasterError("Downloaded instrument master does not look valid.")
        return text

    def load(self, force: bool = False) -> pd.DataFrame:
        if (
            not force
            and self._futures is not None
            and (time.monotonic() - self._loaded_at) <= self.ttl_seconds
        ):
            return self._futures.copy()

        text = self._download()
        self._futures = parse_instrument_master(
            text,
            timezone=self.timezone,
            index_underlyings=self.index_underlyings,
        )
        self._loaded_at = time.monotonic()
        return self._futures.copy()

    def active_futures(
        self,
        as_of: date | None = None,
        current_expiry_only: bool = False,
        include_index: bool = True,
        force: bool = False,
    ) -> pd.DataFrame:
        master = self.load(force=force)
        return select_active_futures(
            master,
            as_of=as_of,
            current_expiry_only=current_expiry_only,
            include_index=include_index,
        )

    def instruments(
        self,
        as_of: date | None = None,
        current_expiry_only: bool = False,
        include_index: bool = True,
        force: bool = False,
    ) -> list[Instrument]:
        return to_instruments(
            self.active_futures(
                as_of=as_of,
                current_expiry_only=current_expiry_only,
                include_index=include_index,
                force=force,
            )
        )
