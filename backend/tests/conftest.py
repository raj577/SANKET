"""Test configuration. Environment is set before any application import."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_STORAGE = Path(tempfile.mkdtemp(prefix="sensibull-test-storage-"))
REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = REPO_ROOT / "sensibull_oi_scan_2026-11-09_12-26.csv"

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET": "test-secret-do-not-use-in-production",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_PATH": str(TEST_STORAGE),
        "COLLECTOR_BOOTSTRAP_TOKEN": "test-collector-token",
        "BOOTSTRAP_ADMIN_EMAIL": "admin@sensibullplatform.com",
        "BOOTSTRAP_ADMIN_PASSWORD": "adminpass123",
        "BOOTSTRAP_ADMIN_NAME": "Test Admin",
        "RATE_LIMIT_ENABLED": "false",
    }
)

COLLECTOR_HEADERS = {"X-Collector-Token": "test-collector-token"}
ADMIN_EMAIL = "admin@sensibullplatform.com"
ADMIN_PASSWORD = "adminpass123"
API = "/api/v1"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app import models  # noqa: F401
    from app.core.config import get_settings
    from app.db.base import Base
    from app.db.session import dispose_engine, get_engine
    from app.main import create_app
    from app.services.csv_storage import reset_storage

    get_settings.cache_clear()
    dispose_engine()
    reset_storage()

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    application = create_app()
    with TestClient(application) as test_client:
        yield test_client

    dispose_engine()


@pytest.fixture()
def admin_headers(client):
    response = client.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def sample_csv_bytes() -> bytes:
    return SAMPLE_CSV.read_bytes()


@pytest.fixture()
def db_session(client):
    from app.db.session import get_sessionmaker

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
