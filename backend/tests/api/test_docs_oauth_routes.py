import httpx

from app.core.security import decrypt_value
from app.models.oauth_token import OAuthToken

TOKENS = {"refresh_token": "rt", "access_token": "at", "expires_in": 3600}


def fake_post_returning(payload, status_code=200, calls=None):
    def _post(url, data=None, **kwargs):
        if calls is not None:
            calls.append(url)
        return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))

    return _post


def _authorize(client):
    response = client.get("/api/docs/google/authorize", follow_redirects=False)
    assert response.status_code == 302
    return response


def test_authorize_requires_auth(client):
    response = client.get("/api/docs/google/authorize", follow_redirects=False)
    assert response.status_code == 401


def test_callback_requires_auth(client):
    response = client.get("/api/docs/google/callback?code=a&state=b", follow_redirects=False)
    assert response.status_code == 401


def test_authorize_redirects_to_google_and_sets_state_cookie(logged_in_client):
    response = _authorize(logged_in_client)
    assert "accounts.google.com" in response.headers["location"]
    state = logged_in_client.cookies.get("google_oauth_state")
    assert state
    assert f"state={state}" in response.headers["location"]
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=600" in set_cookie
    assert "path=/api/docs/google" in set_cookie


def test_callback_stores_token_and_redirects(logged_in_client, db_session, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS))
    response = logged_in_client.get(
        f"/api/docs/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/#/essays?connected=1"
    row = db_session.query(OAuthToken).filter_by(provider="google").one()
    assert decrypt_value(row.encrypted_refresh_token) == "rt"
    assert response.text == ""
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_callback_mismatched_state_is_rejected(logged_in_client, monkeypatch):
    _authorize(logged_in_client)
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    response = logged_in_client.get(
        "/api/docs/google/callback?code=abc&state=wrong", follow_redirects=False
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid oauth state"}
    assert calls == []


def test_callback_missing_state_cookie_is_rejected(logged_in_client, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    response = logged_in_client.get(
        "/api/docs/google/callback?code=abc&state=xyz", follow_redirects=False
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid oauth state"}
    assert calls == []


def test_callback_google_failure_maps_to_502(logged_in_client, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({"error": "invalid_grant"}, 400))
    response = logged_in_client.get(
        f"/api/docs/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "google authorization failed"}
