from fastapi import Depends

from app.api.deps import get_current_user
from app.core.security import create_access_token, create_refresh_token
from app.main import app


def test_login_sets_cookies_on_success(client, seeded_credential):
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    })
    assert response.status_code == 200
    assert response.json() == {"detail": "ok"}
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


def test_login_rejects_bad_password(client, seeded_credential):
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "wrong", "totp_code": "000000",
    })
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


def test_logout_clears_cookies(client, logged_in_client):
    response = logged_in_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.cookies.get("access_token") in (None, "")
    assert "access_token" not in client.cookies
    assert "refresh_token" not in client.cookies


def test_refresh_rotates_access_cookie(logged_in_client):
    response = logged_in_client.post("/api/auth/refresh")
    assert response.status_code == 200
    assert "access_token" in response.cookies


def test_refresh_without_cookie_is_401(client, seeded_credential):
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_rejects_access_token_in_refresh_cookie(client, seeded_credential):
    client.cookies.set("refresh_token", create_access_token("dxwu"))
    assert client.post("/api/auth/refresh").status_code == 401


def test_totp_setup_returns_uri_for_unconfirmed(client, seeded_credential_unconfirmed):
    response = client.post("/api/auth/totp/setup")
    assert response.status_code == 200
    assert response.json()["provisioning_uri"].startswith("otpauth://")


def test_totp_setup_conflicts_when_confirmed(client, seeded_credential):
    response = client.post("/api/auth/totp/setup")
    assert response.status_code == 409
    assert response.json() == {"detail": "totp already confirmed"}


def test_totp_confirm_bad_code(client, seeded_credential_unconfirmed):
    response = client.post("/api/auth/totp/confirm", json={"code": "000000"})
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid code"}


def test_totp_confirm_ok(client, seeded_credential_unconfirmed):
    response = client.post(
        "/api/auth/totp/confirm",
        json={"code": seeded_credential_unconfirmed.current_totp_code()},
    )
    assert response.status_code == 200
    assert response.json() == {"detail": "confirmed"}


def test_get_current_user_dependency(client, seeded_credential):
    @app.get("/api/_test_me")
    def me(user=Depends(get_current_user)):
        return {"username": user.username}

    try:
        assert client.get("/api/_test_me").status_code == 401
        client.cookies.set("access_token", create_refresh_token("dxwu"))
        assert client.get("/api/_test_me").status_code == 401  # wrong type
        client.cookies.set("access_token", create_access_token("dxwu"))
        response = client.get("/api/_test_me")
        assert response.status_code == 200
        assert response.json() == {"username": "dxwu"}
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", "") != "/api/_test_me"
        ]
