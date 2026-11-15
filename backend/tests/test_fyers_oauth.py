"""FYERS OAuth, encrypted token storage and status endpoints.

Everything here runs offline: the FYERS token endpoint is monkeypatched, so no
live credentials, network calls or real tokens are involved.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.timeutils import utcnow

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, API

LOGIN_URL = f"{API}/market/fyers/login-url"
CALLBACK = f"{API}/market/fyers/callback"
STATUS = f"{API}/market/fyers/status"
EXCHANGE = f"{API}/market/fyers/exchange"


@pytest.fixture()
def fyers_settings(monkeypatch, tmp_path):
    """Isolated FYERS configuration: no real app id, token path or key."""
    token_file = tmp_path / "fyers_token.bin"
    monkeypatch.setenv("FYERS_APP_ID", "TESTAPP-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv(
        "FYERS_REDIRECT_URI", "http://localhost:8000/api/v1/market/fyers/callback"
    )
    monkeypatch.setenv("FYERS_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("FYERS_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("FYERS_OAUTH_STATE_TTL_SECONDS", "300")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "fyers")
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


def _user_headers(client) -> dict[str, str]:
    """Create (or reuse) a non-admin user and return its bearer headers."""
    client.post(
        f"{API}/admin/users",
        headers=_admin_headers(client),
        json={
            "name": "Read Only",
            "email": "reader@sensibullplatform.com",
            "password": "readerpass123",
            "role": "USER",
        },
    )
    login = client.post(
        f"{API}/auth/login",
        json={"email": "reader@sensibullplatform.com", "password": "readerpass123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _admin_headers(client) -> dict[str, str]:
    login = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ------------------------------------------------------------------ login URL


def test_login_url_requires_admin(client, fyers_settings):
    assert client.get(LOGIN_URL).status_code == 401
    assert client.get(LOGIN_URL, headers=_user_headers(client)).status_code == 403
    assert client.get(LOGIN_URL, headers=_admin_headers(client)).status_code == 200


def test_login_url_contains_signed_state(client, fyers_settings):
    from app.market_data import fyers_auth

    response = client.get(LOGIN_URL, headers=_admin_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://api-t1.fyers.in/api/v3/generate-authcode?")
    assert "client_id=TESTAPP-100" in body["url"]
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Fmarket%2Ffyers%2Fcallback" in body["url"]
    assert "response_type=code" in body["url"]
    assert body["state"] in body["url"]
    # The state is a real signed token, not a constant.
    claims = fyers_auth.validate_oauth_state(body["state"])
    assert claims["type"] == fyers_auth.STATE_TYPE
    assert body["expires_at"]


def test_login_url_without_credentials_is_reported(client, fyers_settings, monkeypatch):
    monkeypatch.setenv("FYERS_APP_ID", "")
    get_settings.cache_clear()
    response = client.get(LOGIN_URL, headers=_admin_headers(client))
    assert response.status_code == 503
    assert response.json()["code"] == "fyers_not_configured"
    assert "url" not in response.json()


# --------------------------------------------------------------------- state


def test_state_round_trip():
    from app.market_data import fyers_auth

    login = fyers_auth.create_oauth_state(subject="admin-user")
    claims = fyers_auth.validate_oauth_state(login.state)
    assert claims["sub"] == "admin-user"
    assert claims["aud"] == fyers_auth.STATE_AUDIENCE


def test_state_requires_a_value():
    from app.market_data import fyers_auth

    with pytest.raises(fyers_auth.FyersOAuthStateError):
        fyers_auth.validate_oauth_state(None)


def test_expired_state_is_rejected():
    from app.market_data import fyers_auth

    stale = fyers_auth.create_oauth_state(
        ttl_seconds=60, now=utcnow() - timedelta(minutes=10)
    )
    with pytest.raises(fyers_auth.FyersOAuthStateError) as excinfo:
        fyers_auth.validate_oauth_state(stale.state)
    assert "expired" in excinfo.value.message.lower()


def test_tampered_state_is_rejected():
    from app.market_data import fyers_auth

    login = fyers_auth.create_oauth_state()
    tampered = login.state[:-2] + ("aa" if login.state[-2:] != "aa" else "bb")
    with pytest.raises(fyers_auth.FyersOAuthStateError):
        fyers_auth.validate_oauth_state(tampered)


def test_state_signed_with_another_secret_is_rejected(monkeypatch):
    import jwt

    from app.market_data import fyers_auth

    forged = jwt.encode(
        {
            "type": fyers_auth.STATE_TYPE,
            "iss": fyers_auth.STATE_ISSUER,
            "aud": fyers_auth.STATE_AUDIENCE,
            "sub": "attacker",
            "exp": int((utcnow() + timedelta(minutes=5)).timestamp()),
        },
        "not-the-application-secret-padding-0123456789",
        algorithm="HS256",
    )
    with pytest.raises(fyers_auth.FyersOAuthStateError):
        fyers_auth.validate_oauth_state(forged)


# ------------------------------------------------------------------- callback


def test_callback_requires_state(client, fyers_settings):
    response = client.get(CALLBACK, params={"auth_code": "abc123"})
    assert response.status_code == 400
    assert "state" in response.text.lower()
    assert "abc123" not in response.text


def test_callback_rejects_invalid_state(client, fyers_settings):
    response = client.get(CALLBACK, params={"auth_code": "abc123", "state": "garbage"})
    assert response.status_code == 400
    assert "invalid" in response.text.lower()


def test_callback_rejects_expired_state(client, fyers_settings):
    from app.market_data import fyers_auth

    stale = fyers_auth.create_oauth_state(
        ttl_seconds=60, now=utcnow() - timedelta(minutes=10)
    )
    response = client.get(CALLBACK, params={"auth_code": "abc123", "state": stale.state})
    assert response.status_code == 400
    assert "expired" in response.text.lower()


def test_callback_reports_fyers_error_without_storing(client, fyers_settings):
    from pathlib import Path

    from app.market_data import fyers_auth

    login = fyers_auth.create_oauth_state()
    response = client.get(
        CALLBACK,
        params={"s": "error", "message": "app not approved", "state": login.state},
    )
    assert response.status_code == 400
    assert "not completed" in response.text.lower()
    assert not Path(fyers_settings.fyers_token_file).exists()


def test_callback_requires_an_authorization_code(client, fyers_settings):
    from app.market_data import fyers_auth

    login = fyers_auth.create_oauth_state()
    response = client.get(CALLBACK, params={"state": login.state})
    assert response.status_code == 400
    assert "authorization code" in response.text.lower()


def test_callback_prefers_auth_code_over_status_code(client, fyers_settings, monkeypatch):
    """FYERS sends `code=200` (login status) alongside the real `auth_code`.

    Exchanging the status code instead of the authorization code makes every
    login fail with -437 "invalid auth code".
    """
    from app.market_data import fyers_auth

    seen: dict[str, str] = {}

    def fake_exchange(code: str) -> fyers_auth.TokenGrant:
        seen["code"] = code
        return fyers_auth.TokenGrant(access_token="token", expires_in=3600)

    monkeypatch.setattr(fyers_auth, "exchange_auth_code", fake_exchange)

    login = fyers_auth.create_oauth_state()
    response = client.get(
        CALLBACK,
        params={
            "s": "ok",
            "code": "200",
            "auth_code": "real-one-time-code",
            "state": login.state,
        },
    )

    assert response.status_code == 200
    assert seen["code"] == "real-one-time-code"


def test_callback_ignores_a_bare_status_code(client, fyers_settings, monkeypatch):
    """A numeric `code` is the login status, never an exchangeable code."""
    from pathlib import Path

    from app.market_data import fyers_auth

    called = False

    def fake_exchange(code: str) -> fyers_auth.TokenGrant:  # pragma: no cover
        nonlocal called
        called = True
        return fyers_auth.TokenGrant(access_token="token", expires_in=3600)

    monkeypatch.setattr(fyers_auth, "exchange_auth_code", fake_exchange)

    login = fyers_auth.create_oauth_state()
    response = client.get(
        CALLBACK, params={"s": "ok", "code": "200", "state": login.state}
    )

    assert response.status_code == 400
    assert "authorization code" in response.text.lower()
    assert called is False
    assert not Path(fyers_settings.fyers_token_file).exists()


def test_callback_stores_encrypted_token(client, fyers_settings, monkeypatch):
    from pathlib import Path

    from app.market_data import fyers_auth
    from app.market_data.fyers_token_store import FyersTokenStore

    token = "eyJhbGciOiJIUzI1NiJ9.super-secret-fyers-token.signature"
    seen: dict[str, str] = {}

    def fake_exchange(code: str) -> fyers_auth.TokenGrant:
        seen["code"] = code
        return fyers_auth.TokenGrant(access_token=token, expires_in=3600)

    monkeypatch.setattr(fyers_auth, "exchange_auth_code", fake_exchange)

    login = fyers_auth.create_oauth_state()
    response = client.get(
        CALLBACK, params={"auth_code": "code-123", "state": login.state, "s": "ok"}
    )
    assert response.status_code == 200
    assert seen["code"] == "code-123"
    assert "FYERS connected" in response.text
    assert token not in response.text

    path = Path(fyers_settings.fyers_token_file)
    assert path.is_file()
    assert token.encode() not in path.read_bytes()
    assert FyersTokenStore().load() == token

    status = client.get(STATUS, headers=_admin_headers(client))
    assert status.status_code == 200
    body = status.json()
    assert body["token_present"] is True
    assert body["token_valid"] is True
    assert body["reauth_required"] is False
    assert body["source"] == "oauth_callback"
    assert "access_token" not in body
    assert token not in status.text


def test_callback_exchange_failure_is_safe(client, fyers_settings, monkeypatch):
    from pathlib import Path

    from app.market_data import fyers_auth

    def failing_exchange(code: str) -> fyers_auth.TokenGrant:
        raise fyers_auth.FyersAuthError("FYERS rejected the authorization code (400): bad code")

    monkeypatch.setattr(fyers_auth, "exchange_auth_code", failing_exchange)

    login = fyers_auth.create_oauth_state()
    response = client.get(CALLBACK, params={"auth_code": "used-code", "state": login.state})
    assert response.status_code == 400
    assert "already been used" in response.text.lower() or "expired" in response.text.lower()
    assert not Path(fyers_settings.fyers_token_file).exists()


def test_callback_fails_cleanly_when_encryption_key_is_missing(
    client, fyers_settings, monkeypatch
):
    from pathlib import Path

    from app.market_data import fyers_auth

    monkeypatch.setenv("FYERS_TOKEN_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(
        fyers_auth,
        "exchange_auth_code",
        lambda code: fyers_auth.TokenGrant(access_token="tok-abc", expires_in=3600),
    )

    login = fyers_auth.create_oauth_state()
    response = client.get(CALLBACK, params={"auth_code": "c", "state": login.state})
    assert response.status_code == 400
    assert "FYERS_TOKEN_ENCRYPTION_KEY" in response.text
    assert "tok-abc" not in response.text
    # No plaintext fallback: the token must not be written anywhere.
    assert not Path(fyers_settings.fyers_token_file).exists()


# ------------------------------------------------------- exchange + status API


def test_manual_exchange_endpoint_stores_token(client, fyers_settings, monkeypatch):
    from app.market_data import fyers_auth
    from app.market_data.fyers_token_store import FyersTokenStore

    monkeypatch.setattr(
        fyers_auth,
        "exchange_auth_code",
        lambda code: fyers_auth.TokenGrant(access_token="manual-token", expires_in=1800),
    )
    response = client.post(
        EXCHANGE, params={"code": "manual-code"}, headers=_admin_headers(client)
    )
    assert response.status_code == 200
    assert "access_token" not in response.text
    assert FyersTokenStore().load() == "manual-token"


def test_manual_exchange_requires_admin(client, fyers_settings):
    assert client.post(EXCHANGE, params={"code": "x"}).status_code == 401
    assert (
        client.post(EXCHANGE, params={"code": "x"}, headers=_user_headers(client)).status_code
        == 403
    )


def test_status_without_token(client, fyers_settings):
    response = client.get(STATUS, headers=_admin_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["token_present"] is False
    assert body["token_valid"] is False
    assert body["reauth_required"] is True
    assert body["expires_at"] is None
    assert body["authenticated_at"] is None


def test_status_requires_admin(client, fyers_settings):
    assert client.get(STATUS).status_code == 401
    assert client.get(STATUS, headers=_user_headers(client)).status_code == 403


# ------------------------------------------------------------- token storage


def test_token_store_encrypts_at_rest(fyers_settings, tmp_path):
    from app.market_data.fyers_token_store import FyersTokenStore

    store = FyersTokenStore(str(tmp_path / "token.bin"))
    record = store.save("plain-looking-token", expires_in=3600, source="unit-test")
    assert record.expires_at is not None

    raw = (tmp_path / "token.bin").read_bytes()
    assert raw[:1] != b"{"
    assert b"plain-looking-token" not in raw
    assert store.load() == "plain-looking-token"
    assert store.load_record().source == "unit-test"


def test_token_store_refuses_to_write_without_key(fyers_settings, tmp_path, monkeypatch):
    from app.market_data.fyers_token_store import FyersTokenStore, FyersTokenStoreError

    monkeypatch.setenv("FYERS_TOKEN_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    store = FyersTokenStore(str(tmp_path / "token.bin"))
    with pytest.raises(FyersTokenStoreError):
        store.save("token")
    assert not (tmp_path / "token.bin").exists()


def test_token_store_rejects_a_different_key(fyers_settings, tmp_path, monkeypatch):
    from app.market_data.fyers_token_store import FyersTokenStore, FyersTokenStoreError

    store = FyersTokenStore(str(tmp_path / "token.bin"))
    store.save("token")

    monkeypatch.setenv("FYERS_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    with pytest.raises(FyersTokenStoreError):
        store.load_record()
    assert store.status().token_valid is False
    assert store.status().error


def test_expired_token_is_reported(fyers_settings, tmp_path):
    from app.market_data.fyers_token_store import FyersTokenStore

    store = FyersTokenStore(str(tmp_path / "token.bin"))
    store.save("expired-token", expires_at=utcnow() - timedelta(minutes=5))

    status = store.status()
    assert status.token_present is True
    assert status.token_valid is False
    assert status.reauth_required is True
    assert status.seconds_remaining is not None and status.seconds_remaining < 0
    assert "access_token" not in status.as_dict()


def test_expiry_is_read_from_jwt_claim(fyers_settings, tmp_path):
    import jwt

    from app.market_data.fyers_token_store import FyersTokenStore

    expires = utcnow() + timedelta(hours=3)
    token = jwt.encode(
        {"exp": int(expires.timestamp())},
        "fyers-signature-padding-0123456789abcdef",
        algorithm="HS256",
    )
    store = FyersTokenStore(str(tmp_path / "token.bin"))
    record = store.save(token)
    assert record.expires_at is not None
    assert abs((record.expires_at - expires).total_seconds()) < 2


def test_legacy_plaintext_token_is_never_read(fyers_settings, tmp_path):
    import json

    from app.market_data.fyers_token_store import FyersTokenStore, FyersTokenStoreError

    legacy = tmp_path / "token.bin"
    legacy.write_text(json.dumps({"access_token": "legacy-token"}), encoding="utf-8")
    store = FyersTokenStore(str(legacy))
    with pytest.raises(FyersTokenStoreError):
        store.load_record()
    assert store.load() is None
    assert store.status().token_valid is False


def test_delete_removes_the_stored_token(fyers_settings, tmp_path):
    from app.market_data.fyers_token_store import FyersTokenStore

    store = FyersTokenStore(str(tmp_path / "token.bin"))
    store.save("token")
    assert store.delete() is True
    assert store.load() is None
    assert store.delete() is False


def test_provider_status_sees_encrypted_token(fyers_settings, tmp_path):
    from app.market_data import provider
    from app.market_data.fyers_token_store import FyersTokenStore

    _, configured_before, _ = provider.provider_status()
    assert configured_before is False
    FyersTokenStore().save("token")
    _, configured_after, stream_ready = provider.provider_status()
    assert configured_after is True
    assert stream_ready is True


# --------------------------------------------------- token exchange contract


def test_exchange_posts_to_validate_authcode(monkeypatch, fyers_settings):
    """FYERS v3 validates the code at /validate-authcode, never /token.

    Posting to /token returns a blanket 401 (-16) for every request, which
    makes a valid login look like bad credentials.
    """
    import hashlib

    from app.market_data import fyers_auth

    calls: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"s": "ok", "access_token": "access-token", "expires_in": 3600}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["json"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(fyers_auth.httpx, "post", fake_post)

    grant = fyers_auth.exchange_auth_code("fresh-code")

    assert calls["url"] == "https://api-t1.fyers.in/api/v3/validate-authcode"
    body = calls["json"]
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "fresh-code"
    assert body["appIdHash"] == hashlib.sha256(
        b"TESTAPP-100:test-secret-key"
    ).hexdigest()
    assert grant.access_token == "access-token"
    assert grant.expires_in == 3600


def test_exchange_surfaces_fyers_error_message(monkeypatch, fyers_settings):
    from app.market_data import fyers_auth

    class Rejected:
        status_code = 400

        def json(self):
            return {"s": "error", "code": -437, "message": "invalid auth code"}

    monkeypatch.setattr(fyers_auth.httpx, "post", lambda *a, **k: Rejected())

    with pytest.raises(fyers_auth.FyersAuthError) as excinfo:
        fyers_auth.exchange_auth_code("stale-code")
    assert "400" in excinfo.value.message
    assert "invalid auth code" in excinfo.value.message
