"""WebSocket connection hub and best-effort broadcast helpers."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)


class WebSocketHub:
    def __init__(self) -> None:
        self._signals: set[WebSocket] = set()
        self._market: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._set(channel).add(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._set(channel).discard(websocket)

    def _set(self, channel: str) -> set[WebSocket]:
        return self._signals if channel == "signals" else self._market

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, default=str)
        async with self._lock:
            sockets = list(self._set(channel))
        stale: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_text(message)
            except Exception:  # noqa: BLE001 - drop broken sockets only
                stale.append(socket)
        if stale:
            async with self._lock:
                for socket in stale:
                    self._set(channel).discard(socket)


hub = WebSocketHub()


async def broadcast_signal_event(event: str, data: dict[str, Any]) -> None:
    try:
        await hub.broadcast("signals", {"event": event, "data": data})
    except Exception:  # noqa: BLE001 - broadcasting must never break a request
        logger.warning("ws_signal_broadcast_failed", extra={"event": event})
