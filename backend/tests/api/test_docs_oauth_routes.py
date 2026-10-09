from urllib.parse import parse_qs, urlparse

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


def test_callback_google_failure_logs_scrubbed_warning(logged_in_client, monkeypatch, caplog):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({"error": "invalid_grant"}, 400))
    with caplog.at_level("WARNING", logger="app.api.docs"):
        response = logged_in_client.get(
            f"/api/docs/google/callback?code=abc-secret-code&state={state}", follow_redirects=False
        )
    assert response.status_code == 502
    records = [r for r in caplog.records if r.name == "app.api.docs" and r.levelname == "WARNING"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "400" in message
    assert "invalid_grant" not in message
    assert "abc-secret-code" not in message


GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"


def _callback(client, state, code="abc"):
    query = f"state={state}" + (f"&code={code}" if code else "&error=access_denied")
    return client.get(f"/api/docs/google/callback?{query}", follow_redirects=False)


def _stored_scopes(db_session):
    db_session.expire_all()
    return db_session.query(OAuthToken).filter_by(provider="google").one().scopes


def test_callback_stores_granted_scopes_from_token_response(logged_in_client, db_session, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": "only.this"}))
    assert _callback(logged_in_client, state).status_code == 302
    assert _stored_scopes(db_session) == "only.this"


def test_callback_without_scope_field_stores_requested_scopes(logged_in_client, db_session, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS))
    _callback(logged_in_client, state)
    assert _stored_scopes(db_session) == DRIVE


def test_gmail_authorize_requests_gmail_incrementally(logged_in_client):
    response = logged_in_client.get("/api/docs/google/authorize?gmail=true", follow_redirects=False)
    assert response.status_code == 302
    q = parse_qs(urlparse(response.headers["location"]).query)
    assert q["scope"] == [f"{DRIVE} {GMAIL}"]
    assert q["include_granted_scopes"] == ["true"]
    state = logged_in_client.cookies.get("google_oauth_state")
    assert state.startswith("gmail.") and q["state"] == [state]


def test_gmail_callback_stores_granted_scopes_and_returns_to_settings(
    logged_in_client, db_session, monkeypatch
):
    logged_in_client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": f"{GMAIL} {DRIVE}"}))
    response = _callback(logged_in_client, state)
    assert response.status_code == 302
    assert response.headers["location"] == "/#/settings?gmail=1"
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert _stored_scopes(db_session) == f"{GMAIL} {DRIVE}"
    assert logged_in_client.get("/api/settings").json()["gmail_granted"] is True


def test_gmail_callback_when_gmail_was_not_granted(logged_in_client, db_session, monkeypatch):
    logged_in_client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": DRIVE}))
    response = _callback(logged_in_client, state)
    assert response.headers["location"] == "/#/settings?gmail=0"
    assert logged_in_client.get("/api/settings").json()["gmail_granted"] is False


def test_gmail_callback_without_scope_field_falls_back_to_requested(
    logged_in_client, db_session, monkeypatch
):
    logged_in_client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS))
    assert _callback(logged_in_client, state).headers["location"] == "/#/settings?gmail=1"
    assert _stored_scopes(db_session) == f"{DRIVE} {GMAIL}"


def test_gmail_marker_cannot_bypass_state_check(logged_in_client, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    response = _callback(logged_in_client, "gmail." + state)
    assert response.status_code == 400
    assert calls == []


def test_cancelled_consent_stores_nothing_and_returns(logged_in_client, db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    logged_in_client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    response = _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state"), code=None)
    assert response.headers["location"] == "/#/settings?gmail=0"
    _authorize(logged_in_client)
    response = _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state"), code=None)
    assert response.headers["location"] == "/#/essays?connected=0"
    assert calls == []
    assert db_session.query(OAuthToken).count() == 0


def test_cancelled_consent_still_checks_state(logged_in_client):
    _authorize(logged_in_client)
    assert _callback(logged_in_client, "wrong", code=None).status_code == 400
