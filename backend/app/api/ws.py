"""WebSocket channels for live signal and market updates."""
from __future__ import annotations

import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.services.ws_manager import hub

router = APIRouter(prefix="/ws", tags=["websocket"])


async def _serve(websocket: WebSocket, channel: str, token: str | None) -> None:
    if not token:
        await websocket.close(code=4401)
        return
    try:
        decode_token(token, "access")
    except Exception:  # noqa: BLE001 - any invalid token is unauthorized
        await websocket.close(code=4401)
        return

    await hub.connect(channel, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            try:
                payload = json.loads(message)
            except ValueError:
                payload = {}
            if str(payload.get("event", "")).lower() == "ping" or message.strip().lower() == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(channel, websocket)


@router.websocket("/signals")
async def signals_ws(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    await _serve(websocket, "signals", token)


@router.websocket("/market")
async def market_ws(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    await _serve(websocket, "market", token)
