from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends

from app.api.deps import get_current_user
from app.core.config import settings
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


def test_totp_setup_and_confirm_endpoints_are_gone(client, seeded_credential_unconfirmed):
    """Enrollment happens only through the create-user CLI; no unauthenticated API."""
    assert client.post("/api/auth/totp/setup").status_code == 404
    assert client.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 404


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


def _expired_token(token_type, subject="dxwu"):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "type": token_type, "iat": now - timedelta(hours=2),
         "exp": now - timedelta(hours=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture()
def protected_path():
    @app.get("/api/_test_me")
    def me(user=Depends(get_current_user)):
        return {"username": user.username}

    yield "/api/_test_me"
    app.router.routes[:] = [
        r for r in app.router.routes if getattr(r, "path", "") != "/api/_test_me"
    ]


NOT_AUTH = {"detail": "not authenticated"}


def test_protected_rejects_expired_access_token(client, seeded_credential, protected_path):
    client.cookies.set("access_token", _expired_token("access"))
    response = client.get(protected_path)
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_protected_rejects_garbage_token(client, seeded_credential, protected_path):
    client.cookies.set("access_token", "not.a.jwt")
    response = client.get(protected_path)
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_protected_rejects_tampered_token(client, seeded_credential, protected_path):
    token = create_access_token("dxwu")
    client.cookies.set("access_token", token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB"))
    response = client.get(protected_path)
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_protected_rejects_token_for_deleted_user(client, seeded_credential, protected_path):
    client.cookies.set("access_token", create_access_token("ghost"))
    response = client.get(protected_path)
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_refresh_rejects_expired_refresh_token(client, seeded_credential):
    client.cookies.set("refresh_token", _expired_token("refresh"))
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_refresh_rejects_unknown_user(client, seeded_credential):
    client.cookies.set("refresh_token", create_refresh_token("ghost"))
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401
    assert response.json() == NOT_AUTH


def test_login_rejects_correct_password_with_wrong_totp(client, seeded_credential):
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "correct-horse", "totp_code": "000000",
    })
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}
    assert "access_token" not in response.cookies


def test_login_rejects_unconfirmed_account_even_with_correct_password(
    client, seeded_credential_unconfirmed
):
    """Fail closed: no password-only login for an account that never confirmed TOTP."""
    for code in ("", seeded_credential_unconfirmed.current_totp_code()):
        response = client.post("/api/auth/login", json={
            "username": "dxwu", "password": "correct-horse", "totp_code": code,
        })
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid credentials"}
        assert "access_token" not in response.cookies


def test_login_rejects_replayed_totp_code(client, seeded_credential):
    body = {
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    }
    assert client.post("/api/auth/login", json=body).status_code == 200
    client.cookies.clear()
    response = client.post("/api/auth/login", json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}
    assert "access_token" not in response.cookies


def test_login_locks_out_after_five_failures(client, seeded_credential):
    bad = {"username": "dxwu", "password": "wrong", "totp_code": "000000"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    good = {
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    }
    response = client.post("/api/auth/login", json=good)
    assert response.status_code == 429
    assert response.json() == {"detail": "too many attempts"}
    assert response.headers["retry-after"] == "1"
    assert "access_token" not in response.cookies


def test_login_works_again_once_the_backoff_expires(client, seeded_credential, login_throttle_clock):
    bad = {"username": "dxwu", "password": "wrong", "totp_code": "000000"}
    for _ in range(5):
        client.post("/api/auth/login", json=bad)
    login_throttle_clock.advance(2)
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    })
    assert response.status_code == 200


def test_session_cookies_are_httponly_secure_lax(client, seeded_credential, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    })
    assert response.status_code == 200
    set_cookies = response.headers.get_list("set-cookie")
    assert len(set_cookies) == 2
    for header in set_cookies:
        assert "Secure" in header
        assert "HttpOnly" in header
        assert "samesite=lax" in header.lower()


def test_me_returns_username_only(logged_in_client):
    response = logged_in_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"username": "dxwu"}
    assert set(response.json().keys()) == {"username"}


def test_me_requires_auth(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
