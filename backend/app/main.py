"""FastAPI application factory and lifespan wiring."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401 - ensure every model is registered
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.timeutils import utcnow
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.services import settings_service, user_service
from app.workers.price_tracker_worker import start_worker, stop_worker

logger = get_logger(__name__)


def _startup_tasks() -> None:
    settings = get_settings()
    if not settings.is_production:
        # Convenience for local development; production uses Alembic migrations.
        Base.metadata.create_all(get_engine())

    session = get_sessionmaker()()
    try:
        settings_service.ensure_defaults(session)
        admin = user_service.ensure_bootstrap_admin(session)
        if admin is not None:
            logger.info("bootstrap_admin_ready", extra={"email": admin.email})
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _startup_tasks()
    settings = get_settings()
    tracker_task = None
    if settings.environment.lower() != "test":
        tracker_task = start_worker()
    try:
        yield
    finally:
        await stop_worker(tracker_task)
        dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Checksum-SHA256", "X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        database_ok = True
        try:
            session = get_sessionmaker()()
            try:
                session.execute(text("SELECT 1"))
            finally:
                session.close()
        except Exception:  # noqa: BLE001 - report status, never leak details
            database_ok = False
        return {
            "status": "ok" if database_ok else "degraded",
            "database": "ok" if database_ok else "unavailable",
            "environment": settings.environment,
            "time": utcnow(),
        }

    return app


app = create_app()
