from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.core.security import decrypt_value
from app.models.oauth_token import OAuthToken
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import (
    GMAIL_SCOPE,
    GOOGLE_SCOPE,
    exchange_code_for_token,
    get_authorization_url,
    get_valid_access_token,
    granted_scopes,
    is_gmail_granted,
    requested_scope,
    store_token,
)


def fake_post_returning(payload, status_code=200, calls=None):
    def _post(url, data=None, **kwargs):
        if calls is not None:
            calls.append((url, data))
        return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))

    return _post


def test_get_authorization_url_has_required_params():
    url = get_authorization_url("st ate&1")
    parsed = urlparse(url)
    assert parsed.netloc == "accounts.google.com"
    q = parse_qs(parsed.query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [settings.google_client_id]
    assert q["redirect_uri"] == [settings.google_redirect_uri]
    assert q["scope"] == [
        "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"
    ]
    assert "drive.file" in url and "auth%2Fdrive.file" in url
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["st ate&1"]


def test_exchange_code_for_token_calls_google_and_returns_tokens(monkeypatch):
    calls = []
    monkeypatch.setattr(
        httpx,
        "post",
        fake_post_returning(
            {"refresh_token": "rt", "access_token": "at", "expires_in": 3600}, calls=calls
        ),
    )
    result = exchange_code_for_token("some-code")
    assert result["refresh_token"] == "rt"
    assert calls[0][0] == "https://oauth2.googleapis.com/token"
    assert calls[0][1]["code"] == "some-code"
    assert calls[0][1]["grant_type"] == "authorization_code"


def test_exchange_code_non_2xx_raises_without_leaking(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", fake_post_returning({"error": "invalid_grant", "secret": "LEAK"}, 400)
    )
    with pytest.raises(GoogleAuthError) as exc:
        exchange_code_for_token("bad")
    assert "LEAK" not in str(exc.value)


def test_exchange_code_network_error_raises(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(GoogleAuthError):
        exchange_code_for_token("x")


def test_store_token_encrypts_refresh_token(db_session):
    store_token(
        db_session,
        {"refresh_token": "rt", "access_token": "at", "expires_in": 3600},
        scopes="drive.readonly",
    )
    row = db_session.query(OAuthToken).filter_by(provider="google").one()
    assert row.encrypted_refresh_token != b"rt"
    assert decrypt_value(row.encrypted_refresh_token) == "rt"


def test_store_token_upserts_single_row(db_session):
    store_token(db_session, {"refresh_token": "one"}, scopes="a")
    store_token(db_session, {"refresh_token": "two"}, scopes="b")
    rows = db_session.query(OAuthToken).filter_by(provider="google").all()
    assert len(rows) == 1
    assert decrypt_value(rows[0].encrypted_refresh_token) == "two"
    assert rows[0].scopes == "b"


def test_store_token_keeps_existing_refresh_token_when_absent(db_session):
    store_token(db_session, {"refresh_token": "keep"}, scopes="a")
    store_token(db_session, {"access_token": "at"}, scopes="b")
    row = db_session.query(OAuthToken).filter_by(provider="google").one()
    assert decrypt_value(row.encrypted_refresh_token) == "keep"


def test_store_token_without_refresh_token_and_no_row_raises(db_session):
    with pytest.raises(GoogleAuthError):
        store_token(db_session, {"access_token": "at"}, scopes="a")


def test_get_valid_access_token_raises_when_not_connected(db_session):
    with pytest.raises(GoogleAuthError):
        get_valid_access_token(db_session)


def test_get_valid_access_token_refreshes(db_session, monkeypatch):
    store_token(db_session, {"refresh_token": "rt"}, scopes="a")
    calls = []
    monkeypatch.setattr(
        httpx,
        "post",
        fake_post_returning({"access_token": "fresh", "expires_in": 3600}, calls=calls),
    )
    assert get_valid_access_token(db_session) == "fresh"
    assert calls[0][1]["grant_type"] == "refresh_token"
    assert calls[0][1]["refresh_token"] == "rt"


def test_get_valid_access_token_raises_when_refresh_fails(db_session, monkeypatch):
    store_token(db_session, {"refresh_token": "rt"}, scopes="a")
    monkeypatch.setattr(httpx, "post", fake_post_returning({"error": "invalid_grant"}, 400))
    with pytest.raises(GoogleAuthError):
        get_valid_access_token(db_session)


GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"


def test_default_authorization_url_never_asks_for_gmail():
    q = parse_qs(urlparse(get_authorization_url("s")).query)
    assert "gmail" not in q["scope"][0]
    assert "include_granted_scopes" not in q


def test_gmail_authorization_url_adds_readonly_scope_incrementally():
    q = parse_qs(urlparse(get_authorization_url("s", gmail=True)).query)
    assert q["scope"] == [f"{DRIVE} {GMAIL}"]
    assert q["include_granted_scopes"] == ["true"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert "gmail.send" not in q["scope"][0] and "gmail.modify" not in q["scope"][0]


def test_requested_scope():
    assert requested_scope() == GOOGLE_SCOPE == DRIVE
    assert requested_scope(gmail=True) == f"{DRIVE} {GMAIL}"
    assert GMAIL_SCOPE == GMAIL


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        # Google reports what was actually granted, in its own order.
        ({"scope": f"{GMAIL} {DRIVE}"}, f"{GMAIL} {DRIVE}"),
        # The user unticked Gmail on the granular consent screen.
        ({"scope": DRIVE}, DRIVE),
        ({"scope": f"  {GMAIL}\n"}, GMAIL),
        ({}, "requested scopes"),
        ({"scope": ""}, "requested scopes"),
        ({"scope": "   "}, "requested scopes"),
        ({"scope": None}, "requested scopes"),
        ({"scope": ["not", "a", "string"]}, "requested scopes"),
    ],
)
def test_granted_scopes(response, expected):
    assert granted_scopes(response, "requested scopes") == expected


def test_is_gmail_granted(db_session):
    assert is_gmail_granted(db_session) is False
    store_token(db_session, {"refresh_token": "rt"}, scopes=DRIVE)
    assert is_gmail_granted(db_session) is False
    store_token(db_session, {}, scopes=f"{DRIVE} {GMAIL}")
    assert is_gmail_granted(db_session) is True
    # A substring of another scope does not count.
    store_token(db_session, {}, scopes=f"{GMAIL}.extra")
    assert is_gmail_granted(db_session) is False
