from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, auth, collector, market, signals, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(collector.router)
api_router.include_router(signals.router)
api_router.include_router(market.router)
api_router.include_router(ws.router)
