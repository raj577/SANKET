"""Application configuration loaded from environment variables."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Core -------------------------------------------------------------
    app_name: str = "OI Intelligence Platform"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"

    # --- Database ---------------------------------------------------------
    database_url: str = (
        "postgresql+psycopg://sensibull:sensibull@localhost:5432/sensibull"
    )
    database_echo: bool = False

    # --- Auth -------------------------------------------------------------
    jwt_secret: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        description="Override in production. A random value invalidates tokens on restart.",
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 14
    password_min_length: int = 8

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "Administrator"

    # Collector authentication. Either a bootstrap shared secret (development)
    # or revocable database-backed tokens created via the CLI.
    collector_bootstrap_token: str | None = None

    # --- CORS -------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # --- CSV storage ------------------------------------------------------
    storage_backend: str = "local"
    storage_local_path: str = "storage/sensibull"
    storage_max_csv_bytes: int = 25 * 1024 * 1024
    storage_retention_enabled: bool = False
    storage_retention_days: int = 3650

    # S3 / R2 compatible storage (optional)
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "auto"
    s3_prefix: str = "sensibull"

    # --- Scanner ----------------------------------------------------------
    scanner_min_grade: str = "C"
    scanner_allow_publish_without_stop_loss: bool = False

    # --- FYERS ------------------------------------------------------------
    fyers_app_id: str | None = None
    fyers_secret_key: str | None = None
    fyers_redirect_uri: str = "http://localhost:8000/api/v1/market/fyers/callback"
    fyers_access_token: str | None = None
    fyers_token_file: str = "storage/fyers_token.json"
    fyers_api_base: str = "https://api-t1.fyers.in/api/v3"
    fyers_data_base: str = "https://api-t1.fyers.in/data"
    price_persist_interval_seconds: int = 60
    price_stale_after_seconds: int = 300
    tracking_poll_seconds: int = 15

    # --- Rate limiting (single-process, best effort) ----------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    login_rate_limit_per_minute: int = 10

    # --- WebSocket --------------------------------------------------------
    ws_publish_interval_seconds: int = 5

    @field_validator("storage_backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"local", "s3"}:
            raise ValueError("storage_backend must be 'local' or 's3'")
        return value

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.is_production:
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production")
            if "change-me" in self.jwt_secret.lower():
                raise ValueError("JWT_SECRET still contains a placeholder value")
            if any(origin.strip() == "*" for origin in self.cors_origins_list):
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def resolve_local_path(self) -> Path:
        return Path(self.storage_local_path).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
