"""Minimal FYERS v3 REST client used by the price tracker worker.

Credentials and tokens stay on the backend. This module performs no order
placement and exposes only market-data reads.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class FyersError(RuntimeError):
    pass


class FyersTokenStore:
    def __init__(self, path: str | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.fyers_token_file)

    def save(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"access_token": token}).encode("utf-8")
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - Windows best effort
            pass

    def load(self) -> str | None:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data.get("access_token")
        except (OSError, ValueError):
            return None


class FyersClient:
    def __init__(self, access_token: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self.base = settings.fyers_data_base.rstrip("/")
        self.app_id = settings.fyers_app_id
        self.token = access_token or settings.fyers_access_token or FyersTokenStore().load()
        self.client = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if not self.app_id or not self.token:
            raise FyersError("FYERS is not configured")
        return {"Authorization": f"{self.app_id}:{self.token}", "Content-Type": "application/json"}

    def quotes(self, symbols: list[str]) -> list[dict]:
        if not symbols:
            return []
        joined = ",".join(symbols)
        response = self.client.get(
            f"{self.base}/quotes",
            params={"symbols": joined},
            headers=self._headers(),
        )
        if response.status_code == 401:
            raise FyersError("FYERS token expired")
        response.raise_for_status()
        payload = response.json()
        if payload.get("s") != "ok":
            raise FyersError(payload.get("message", "FYERS quote request failed"))
        return payload.get("d", [])

    def ltp_map(self, symbols: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in self.quotes(symbols):
            symbol = item.get("n") or item.get("symbol")
            ltp = (item.get("v") or {}).get("lp")
            if symbol and ltp is not None:
                result[symbol] = float(ltp)
        return result

    def close(self) -> None:
        self.client.close()
