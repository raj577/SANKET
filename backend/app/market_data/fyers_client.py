"""Minimal FYERS v3 REST client used by the price tracker worker and scanners.

Credentials and tokens stay on the backend. This module performs no order
placement and exposes only market-data and profile reads.

Token resolution order: explicit argument, ``FYERS_ACCESS_TOKEN`` environment
override (development only), then the encrypted token file written by the OAuth
callback.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.market_data.fyers_token_store import (  # noqa: F401 - re-exported for compatibility
    FyersTokenRecord,
    FyersTokenStatus,
    FyersTokenStore,
    FyersTokenStoreError,
)

logger = get_logger(__name__)


class FyersError(RuntimeError):
    pass


TOKEN_EXPIRED_MESSAGE = (
    "FYERS access token expired or was rejected; re-authenticate at "
    "/api/v1/market/fyers/login-url"
)


class FyersClient:
    def __init__(self, access_token: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self.base = settings.fyers_data_base.rstrip("/")
        self.api_base = settings.fyers_api_base.rstrip("/")
        self.app_id = settings.fyers_app_id
        self.token = access_token or settings.fyers_access_token or FyersTokenStore().load()
        self.client = httpx.Client(timeout=timeout)

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.token)

    def _headers(self) -> dict[str, str]:
        if not self.app_id or not self.token:
            raise FyersError("FYERS is not configured")
        return {"Authorization": f"{self.app_id}:{self.token}", "Content-Type": "application/json"}

    def _get(self, url: str, params: dict | None = None, *, allow_no_data: bool = False) -> dict:
        try:
            response = self.client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            raise FyersError(f"FYERS request failed: {type(exc).__name__}") from exc
        if response.status_code == 401:
            raise FyersError(TOKEN_EXPIRED_MESSAGE)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FyersError(f"FYERS request failed with status {response.status_code}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise FyersError("FYERS returned a non-JSON response") from exc
        if not isinstance(payload, dict) or payload.get("s") != "ok":
            # FYERS answers an empty history range with ``s="no_data"`` and a
            # blank message. That is a normal empty result for contracts whose
            # first candle starts inside the requested lookback, not a failure.
            if allow_no_data and isinstance(payload, dict) and payload.get("s") == "no_data":
                return payload
            message = payload.get("message") if isinstance(payload, dict) else ""
            if not message:
                status = payload.get("s") if isinstance(payload, dict) else None
                code = payload.get("code") if isinstance(payload, dict) else None
                message = f"FYERS request failed (s={status}, code={code})"
            raise FyersError(str(message))
        return payload

    def profile(self) -> dict:
        """Authenticated account profile; a cheap way to validate the token."""
        return self._get(f"{self.api_base}/profile")

    def quotes(self, symbols: list[str]) -> list[dict]:
        if not symbols:
            return []
        payload = self._get(f"{self.base}/quotes", {"symbols": ",".join(symbols)})
        return payload.get("d", [])

    def ltp_map(self, symbols: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in self.quotes(symbols):
            symbol = item.get("n") or item.get("symbol")
            ltp = (item.get("v") or {}).get("lp")
            if symbol and ltp is not None:
                result[symbol] = float(ltp)
        return result

    def history(
        self,
        symbol: str,
        *,
        resolution: str = "D",
        range_from: str = "",
        range_to: str = "",
        date_format: str = "0",
        cont_flag: str = "1",
    ) -> dict:
        """Historical candles. ``date_format=0`` means epoch seconds."""
        return self._get(
            f"{self.base}/history",
            {
                "symbol": symbol,
                "resolution": resolution,
                "date_format": date_format,
                "range_from": range_from,
                "range_to": range_to,
                "cont_flag": cont_flag,
            },
            allow_no_data=True,
        )

    def option_chain(
        self,
        symbol: str,
        *,
        strikecount: int = 10,
        timestamp: str | int = "",
        greeks: bool = False,
    ) -> dict:
        """Fetch the FYERS option chain for one underlying.

        ``symbol`` is the underlying (e.g. ``NSE:NIFTY50-INDEX`` or
        ``NSE:SBIN-EQ``). The response carries per-strike ``oi`` and ``oich``
        (open-interest change).
        """
        return self._get(
            f"{self.base}/options-chain-v3",
            {
                "symbol": symbol,
                "strikecount": int(strikecount),
                "timestamp": timestamp,
                "greeks": "1" if greeks else "0",
            },
        )

    def close(self) -> None:
        self.client.close()
