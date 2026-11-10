"""Database-backed collector tokens and revocation."""
from __future__ import annotations

from app.core.security import token_digest
from app.models.collector import CollectorToken

from .conftest import API


def test_database_collector_token_works_and_can_be_revoked(client, db_session):
    raw = "col_test_database_token_123"
    db_session.add(
        CollectorToken(name="test-collector", token_hash=token_digest(raw), is_active=True)
    )
    db_session.commit()
    headers = {"X-Collector-Token": raw}

    first = client.get(f"{API}/collector/status", headers=headers)
    assert first.status_code == 200
    assert first.json()["collector_authenticated"] is True

    # A second call exercises last_seen_at comparison against the database value.
    second = client.get(f"{API}/collector/status", headers=headers)
    assert second.status_code == 200

    token = db_session.query(CollectorToken).filter_by(name="test-collector").one()
    token.is_active = False
    db_session.commit()

    denied = client.get(f"{API}/collector/status", headers=headers)
    assert denied.status_code == 401
