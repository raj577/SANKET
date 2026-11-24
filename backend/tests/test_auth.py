"""Authentication and authorization behaviour."""
from __future__ import annotations

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, API


def test_admin_bootstrap_login_and_me(client):
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL
    assert me.json()["role"] == "ADMIN"


def test_invalid_password_is_rejected(client):
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_refresh_token_rotates_on_each_use(client):
    login = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    ).json()
    first_refresh = login["refresh_token"]

    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first_refresh

    second = client.post(
        f"{API}/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert second.status_code == 200
    assert second.json()["refresh_token"] not in {
        first_refresh,
        rotated.json()["refresh_token"],
    }


def test_concurrent_refresh_of_same_token_keeps_session_alive(client):
    login = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    ).json()

    # Two requests racing to refresh the same cookie must both succeed.
    first = client.post(f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]})
    second = client.post(f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["refresh_token"] != second.json()["refresh_token"]

    for pair in (first.json(), second.json()):
        me = client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
        )
        assert me.status_code == 200

    # The raced-again token still works: the race must not have revoked it.
    third = client.post(
        f"{API}/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert third.status_code == 200


def test_reusing_a_rotated_token_after_the_grace_window_revokes_the_family(
    client, db_session
):
    from datetime import timedelta

    from app.core.timeutils import utcnow
    from app.models.user import RefreshToken

    login = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    ).json()
    first_refresh = login["refresh_token"]

    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200

    # Backdate the rotation beyond the race window: this is now plain reuse.
    stored = db_session.query(RefreshToken).filter(RefreshToken.replaced_by.isnot(None)).one()
    stored.revoked_at = utcnow() - timedelta(days=1)
    db_session.commit()

    reused = client.post(f"{API}/auth/refresh", json={"refresh_token": first_refresh})
    assert reused.status_code == 401

    # Reuse is treated as token theft: the whole session family is revoked,
    # including access tokens already issued and the newest refresh token.
    after_reuse = client.post(
        f"{API}/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert after_reuse.status_code == 401
    access_after_reuse = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert access_after_reuse.status_code == 401


def test_logout_revokes_access_and_refresh_tokens(client):
    login = client.post(
        f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    ).json()
    access = login["access_token"]
    refresh = login["refresh_token"]

    logout = client.post(f"{API}/auth/logout", json={"refresh_token": refresh})
    assert logout.status_code == 200

    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 401
    refreshed = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 401


def test_last_admin_cannot_be_demoted(client, admin_headers):
    me = client.get(f"{API}/auth/me", headers=admin_headers).json()
    response = client.patch(
        f"{API}/admin/users/{me['id']}", headers=admin_headers, json={"role": "USER"}
    )
    assert response.status_code == 409


def test_admin_routes_require_admin_role(client, admin_headers):
    created = client.post(
        f"{API}/admin/users",
        headers=admin_headers,
        json={
            "name": "Regular User",
            "email": "user@sensibullplatform.com",
            "password": "userpass123",
            "role": "USER",
        },
    )
    assert created.status_code == 201

    login = client.post(
        f"{API}/auth/login", json={"email": "user@sensibullplatform.com", "password": "userpass123"}
    )
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get(f"{API}/admin/overview", headers=user_headers).status_code == 403
    assert client.get(f"{API}/admin/overview", headers=admin_headers).status_code == 200
    assert client.get(f"{API}/signals", headers=user_headers).status_code == 200
    assert client.get(f"{API}/signals").status_code in {401, 403}
