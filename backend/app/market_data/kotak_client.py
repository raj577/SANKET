"""Kotak Neo market-data client.

REST quotes and the scrip master authenticate with the consumer key alone, so
they work without TOTP/MPIN. The SFeed websocket additionally needs a
TOTP/MPIN session, which is only created when the streaming worker asks for an
authenticated SDK. No order placement is performed.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

QUOTE_CHUNK_SIZE = 50

INDEX_TOKENS: dict[str, tuple[str, str]] = {
    "NIFTY": ("nse_cm", "Nifty 50"),
    "BANKNIFTY": ("nse_cm", "Nifty Bank"),
    "FINNIFTY": ("nse_cm", "Nifty Fin Service"),
    "MIDCPNIFTY": ("nse_cm", "NIFTY MID SELECT"),
    "INDIAVIX": ("nse_cm", "INDIA VIX"),
    "SENSEX": ("bse_cm", "SENSEX"),
}

_TRADING_SUFFIXES = ("-EQ", "-BE", "-BL", "-BZ")


class KotakError(RuntimeError):
    pass


def normalize_symbol(value: str | None) -> str:
    return (value or "").strip().upper()


def normalize_segment(value: str | None) -> str:
    return (value or "").strip().lower()


def base_symbol(trading_symbol: str | None) -> str | None:
    """Turn ``WIPRO-EQ`` into ``WIPRO``; indices are returned unchanged."""
    name = normalize_symbol(trading_symbol)
    if not name:
        return None
    for suffix in _TRADING_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def normalize_mobile(value: str | None) -> str | None:
    """Kotak expects the country code; accept a bare 10-digit number too."""
    mobile = (value or "").strip().replace(" ", "")
    if not mobile:
        return None
    if mobile.startswith("+"):
        return mobile
    if mobile.isdigit() and len(mobile) == 10:
        return f"+91{mobile}"
    if mobile.isdigit() and len(mobile) == 12 and mobile.startswith("91"):
        return f"+{mobile}"
    return mobile


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


class KotakScripMaster:
    """Maps app symbols to Kotak ``(exchange_segment, pSymbol)`` pairs.

    The CSV is cached for the calendar day; a failed refresh keeps the stale
    file so a broker outage does not stop price tracking.
    """

    def __init__(self, path: str | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.kotak_scrip_cache_path)
        self._symbols: dict[str, tuple[str, str]] | None = None
        self._trading: dict[str, str] | None = None

    def ensure_loaded(self, sdk) -> None:
        if self._symbols is not None:
            return
        if not self._cache_is_fresh():
            try:
                self._download(sdk)
            except Exception as exc:  # noqa: BLE001 - stale cache is still useful
                logger.warning(
                    "kotak_scrip_master_refresh_failed", extra={"error": str(exc)}
                )
        if not self.path.is_file():
            raise KotakError(
                "Kotak scrip master is unavailable; check the consumer key and retry"
            )
        self._parse(self.path.read_text(encoding="utf-8", errors="replace"))

    def token_for(self, symbol: str) -> tuple[str, str] | None:
        key = normalize_symbol(symbol)
        if key in INDEX_TOKENS:
            return INDEX_TOKENS[key]
        return (self._symbols or {}).get(key)

    def symbol_for_trading_symbol(self, trading_symbol: str | None) -> str | None:
        name = normalize_symbol(trading_symbol)
        if not name:
            return None
        direct = (self._trading or {}).get(name)
        if direct:
            return direct
        return base_symbol(name)

    def _cache_is_fresh(self) -> bool:
        if not self.path.is_file():
            return False
        modified = datetime.fromtimestamp(self.path.stat().st_mtime).date()
        return modified == date.today()

    def _download(self, sdk) -> None:
        response = sdk.scrip_master(exchange_segment="nse_cm")
        url = self._select_url(response)
        payload = httpx.get(url, timeout=60, follow_redirects=True)
        payload.raise_for_status()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(payload.content)
        tmp.replace(self.path)

    @staticmethod
    def _select_url(response) -> str:
        candidates: list[str] = []
        if isinstance(response, str):
            candidates = [response]
        elif isinstance(response, dict):
            data = response.get("data") if isinstance(response.get("data"), dict) else response
            values = data.get("filesPaths") or data.get("filespaths") or data.get("filesPaths".lower())
            if isinstance(values, str):
                candidates = [values]
            elif isinstance(values, list):
                candidates = [str(item) for item in values]
        urls = [item for item in candidates if item.lower().endswith(".csv")]
        for url in urls:
            if "nse_cm" in url.lower():
                return url
        if urls:
            return urls[0]
        raise KotakError("Kotak scrip master returned no CSV download URL")

    def _parse(self, text: str) -> None:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if not reader.fieldnames:
            raise KotakError("Kotak scrip master CSV has no header row")
        fields = {name.strip().lower(): name for name in reader.fieldnames}

        def pick(row: dict, *names: str) -> str | None:
            for name in names:
                column = fields.get(name)
                if column is not None:
                    value = row.get(column)
                    if value not in (None, ""):
                        return str(value)
            return None

        symbols: dict[str, tuple[str, str]] = {}
        preferred: set[str] = set()
        trading: dict[str, str] = {}

        for row in reader:
            token = pick(row, "psymbol")
            trading_symbol = pick(row, "ptrdsymbol", "p_trd_symbol")
            if not token or not trading_symbol:
                continue
            segment = pick(row, "pexchseg", "p_exch_seg") or "nse_cm"
            base = base_symbol(trading_symbol)
            if not base:
                continue
            trading[normalize_symbol(trading_symbol)] = base
            is_eq = normalize_symbol(trading_symbol).endswith("-EQ")
            if base not in symbols or (is_eq and base not in preferred):
                symbols[base] = (normalize_segment(segment) or "nse_cm", str(token))
                if is_eq:
                    preferred.add(base)
            symbol_name = pick(row, "psymbolname", "p_symbol_name")
            if symbol_name:
                alias = normalize_symbol(symbol_name)
                if alias and alias not in symbols:
                    symbols[alias] = symbols[base]

        if not symbols:
            raise KotakError("Kotak scrip master contains no usable equity symbols")
        self._symbols = symbols
        self._trading = trading


class KotakClient:
    """Small provider used by both the REST poller and the stream worker."""

    def __init__(
        self,
        *,
        sdk_factory: Callable[[], object] | None = None,
        master: KotakScripMaster | None = None,
        consumer_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self.consumer_key = consumer_key or settings.kotak_consumer_key
        self.environment = settings.kotak_environment
        self.quote_type = settings.kotak_quote_type or "ltp"
        self._sdk_factory = sdk_factory
        self._sdk: object | None = None
        self._session_ready = False
        self.master = master or KotakScripMaster()

    @property
    def configured(self) -> bool:
        return bool(self.consumer_key)

    @property
    def stream_ready(self) -> bool:
        settings = get_settings()
        return self.configured and all(
            [
                settings.kotak_mobile_number,
                settings.kotak_ucc,
                settings.kotak_mpin,
                settings.kotak_totp_secret,
            ]
        )

    # ------------------------------------------------------------------ SDK
    def sdk(self):
        if self._sdk is None:
            if not self.configured:
                raise KotakError("Kotak consumer key is not configured")
            if self._sdk_factory is not None:
                self._sdk = self._sdk_factory()
            else:
                try:
                    from neo_api_client import NeoAPI
                except ImportError as exc:  # pragma: no cover - dependency guard
                    raise KotakError(
                        "kotakneoapi is not installed; run pip install -r requirements.txt"
                    ) from exc
                self._sdk = NeoAPI(
                    consumer_key=self.consumer_key, environment=self.environment
                )
        return self._sdk

    def authenticated_sdk(self):
        """Create a TOTP + MPIN session required by the SFeed websocket."""
        sdk = self.sdk()
        if self._session_ready:
            return sdk
        settings = get_settings()
        if not self.stream_ready:
            raise KotakError(
                "Kotak streaming credentials are incomplete "
                "(mobile number, UCC, MPIN and TOTP secret are required)"
            )
        try:
            import pyotp
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise KotakError("pyotp is not installed; run pip install -r requirements.txt") from exc

        totp = pyotp.TOTP((settings.kotak_totp_secret or "").replace(" ", "")).now()
        login = sdk.totp_login(
            mobile_number=normalize_mobile(settings.kotak_mobile_number),
            ucc=settings.kotak_ucc,
            totp=totp,
        )
        self._raise_on_error(login, "TOTP login")
        validate = sdk.totp_validate(mpin=settings.kotak_mpin)
        self._raise_on_error(validate, "MPIN validation")
        self._session_ready = True
        return sdk

    @staticmethod
    def _raise_on_error(response, step: str) -> None:
        if not isinstance(response, dict):
            return
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        status = str(response.get("status") or data.get("status") or "").lower()
        if status == "error" or str(response.get("stat") or "").lower() == "not_ok":
            message = (
                response.get("message")
                or response.get("emsg")
                or data.get("message")
                or "unknown error"
            )
            raise KotakError(f"Kotak {step} failed: {message}")

    # -------------------------------------------------------------- quotes
    def ltp_map(self, symbols: list[str]) -> dict[str, float]:
        """Return ``{app_symbol: ltp}`` for the symbols Kotak resolved."""
        if not symbols:
            return {}
        sdk = self.sdk()
        self.master.ensure_loaded(sdk)

        resolved: list[tuple[str, tuple[str, str]]] = []
        for symbol in symbols:
            key = normalize_symbol(symbol)
            token = self.master.token_for(key)
            if token is not None:
                resolved.append((key, token))

        prices: dict[str, float] = {}
        for chunk in _chunks(resolved, QUOTE_CHUNK_SIZE):
            payload = [
                {"instrument_token": token, "exchange_segment": segment}
                for _, (segment, token) in chunk
            ]
            response = sdk.quotes(instrument_tokens=payload, quote_type=self.quote_type)
            self._raise_on_error(response, "quote")
            rows = response if isinstance(response, list) else response.get("data") or []
            by_token = {
                str(item.get("exchange_token")): item
                for item in rows
                if isinstance(item, dict)
            }
            for key, (_, token) in chunk:
                row = by_token.get(str(token))
                if row is None:
                    continue
                ltp = row.get("ltp")
                if ltp in (None, ""):
                    continue
                try:
                    prices[key] = float(ltp)
                except (TypeError, ValueError):
                    continue
        return prices

    def active_token_map(self, symbols: list[str]) -> dict[tuple[str, str], str]:
        """Map subscribed ``(segment, token)`` pairs back to app symbols."""
        self.master.ensure_loaded(self.sdk())
        result: dict[tuple[str, str], str] = {}
        for symbol in symbols:
            key = normalize_symbol(symbol)
            token = self.master.token_for(key)
            if token is not None:
                result[token] = key
        return result

    def symbol_for_message(
        self, exchange_segment: str, instrument_token, trading_symbol=None
    ) -> str | None:
        name = normalize_symbol(trading_symbol)
        if name:
            for app_symbol, (_, index_name) in INDEX_TOKENS.items():
                if normalize_symbol(index_name) == name:
                    return app_symbol
        return self.master.symbol_for_trading_symbol(trading_symbol) or base_symbol(
            trading_symbol
        )

    def close(self) -> None:
        # The SDK owns a shared HTTP session; no explicit close is required.
        return None
