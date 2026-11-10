"""Structured JSON logging configuration."""
from __future__ import annotations

import logging
import sys

from pythonjsonlogger import jsonlogger

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        json_default=str,
    )
    handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(handler)

    # Never let noisy third-party loggers leak request bodies.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
