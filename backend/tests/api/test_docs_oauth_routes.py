from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.security import decrypt_value
from app.models.gmail_account import GmailAccount
from app.models.oauth_token import OAuthToken
from app.services.google_docs_service import store_token
from tests.services.gmail.fakes import grant_gmail

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


def _gmail_authorize(client):
    response = client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    assert response.status_code == 302
    return response


def _accounts(db_session):
    db_session.expire_all()
    return db_session.query(GmailAccount).order_by(GmailAccount.id).all()


def test_gmail_authorize_asks_for_gmail_only_with_the_account_chooser(logged_in_client):
    response = logged_in_client.get("/api/docs/google/authorize?gmail=true", follow_redirects=False)
    assert response.status_code == 302
    q = parse_qs(urlparse(response.headers["location"]).query)
    assert q["scope"] == [GMAIL]
    assert q["prompt"] == ["consent select_account"]
    assert q["access_type"] == ["offline"]
    assert "include_granted_scopes" not in q
    state = logged_in_client.cookies.get("google_oauth_state")
    assert state.startswith("gmail.") and q["state"] == [state]


def test_gmail_callback_adds_the_inbox_by_its_address(logged_in_client, db_session, monkeypatch, gmail_profile):
    gmail_profile.address = "You@School.EDU"
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": GMAIL}))

    response = _callback(logged_in_client, state)

    assert response.status_code == 302
    assert response.headers["location"] == "/#/settings?gmail=1"
    assert "max-age=0" in response.headers["set-cookie"].lower()
    # The profile was read with the consent's own access token.
    assert gmail_profile.tokens == ["Bearer at"]
    (account,) = _accounts(db_session)
    assert account.email == "you@school.edu" and account.scopes == GMAIL
    assert decrypt_value(account.encrypted_refresh_token) == "rt"
    # The Drive/Docs connection is not involved.
    assert db_session.query(OAuthToken).count() == 0
    settings = logged_in_client.get("/api/settings").json()
    assert settings["gmail_granted"] is True and settings["google_connected"] is False


def test_another_inbox_is_added_and_the_drive_row_is_untouched(logged_in_client, db_session, monkeypatch, gmail_profile):
    store_token(db_session, {"refresh_token": "drive-rt"}, scopes=DRIVE)
    for address, refresh in (("me@gmail.com", "rt-1"), ("me@school.edu", "rt-2")):
        gmail_profile.address = address
        _gmail_authorize(logged_in_client)
        monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "refresh_token": refresh, "scope": GMAIL}))
        assert _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state")).status_code == 302

    assert [(a.email, decrypt_value(a.encrypted_refresh_token)) for a in _accounts(db_session)] == [
        ("me@gmail.com", "rt-1"),
        ("me@school.edu", "rt-2"),
    ]
    drive = db_session.query(OAuthToken).filter_by(provider="google").one()
    assert drive.scopes == DRIVE and decrypt_value(drive.encrypted_refresh_token) == "drive-rt"


def test_reconnect_replaces_the_inbox_token_and_clears_its_error(logged_in_client, db_session, monkeypatch, gmail_profile):
    old = grant_gmail(db_session, "me@gmail.com", refresh_token="old")
    old.last_error = "google token request rejected (status 400); reconnect this inbox in Settings"
    db_session.commit()
    gmail_profile.address = "ME@gmail.com"
    _gmail_authorize(logged_in_client)
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "refresh_token": "new", "scope": GMAIL}))

    assert _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state")).headers["location"] == (
        "/#/settings?gmail=1"
    )

    (account,) = _accounts(db_session)
    assert account.id == old.id
    assert decrypt_value(account.encrypted_refresh_token) == "new" and account.last_error is None


def test_gmail_callback_when_gmail_was_not_granted(logged_in_client, db_session, monkeypatch, gmail_profile):
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": "openid"}))
    response = _callback(logged_in_client, state)
    assert response.headers["location"] == "/#/settings?gmail=0"
    assert gmail_profile.tokens == []  # Gmail isn't asked without the permission
    assert _accounts(db_session) == [] and db_session.query(OAuthToken).count() == 0
    assert logged_in_client.get("/api/settings").json()["gmail_granted"] is False


def test_gmail_callback_without_scope_field_falls_back_to_requested(logged_in_client, db_session, monkeypatch):
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS))
    assert _callback(logged_in_client, state).headers["location"] == "/#/settings?gmail=1"
    assert [a.scopes for a in _accounts(db_session)] == [GMAIL]


@pytest.mark.parametrize("profile_status", [401, 500])
def test_gmail_callback_profile_failure_stores_nothing(logged_in_client, db_session, monkeypatch, gmail_profile, caplog, profile_status):
    gmail_profile.status = profile_status
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "access_token": "ya29.secret", "scope": GMAIL}))
    with caplog.at_level("WARNING", logger="app.api.docs"):
        response = _callback(logged_in_client, state)
    assert response.status_code == 502
    assert response.json() == {"detail": "google authorization failed"}
    assert _accounts(db_session) == []
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert f"status {profile_status}" in logged
    assert "ya29.secret" not in logged and "secret body text" not in logged


@pytest.mark.parametrize(
    "token_response",
    [
        {"refresh_token": "rt", "scope": GMAIL},  # no access token to read the profile with
        {"access_token": "at", "scope": GMAIL},  # a new inbox needs a refresh token
    ],
)
def test_gmail_callback_with_an_incomplete_token_response_stores_nothing(
    logged_in_client, db_session, monkeypatch, token_response
):
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    monkeypatch.setattr(httpx, "post", fake_post_returning(token_response))
    assert _callback(logged_in_client, state).status_code == 502
    assert _accounts(db_session) == []


def test_gmail_callback_refuses_an_unusable_address(logged_in_client, db_session, monkeypatch, gmail_profile):
    gmail_profile.address = "not an address"
    _gmail_authorize(logged_in_client)
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": GMAIL}))
    assert _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state")).status_code == 502
    assert _accounts(db_session) == []


def test_connect_google_docs_no_longer_affects_gmail(logged_in_client, db_session, monkeypatch, gmail_profile):
    grant_gmail(db_session, "me@gmail.com")
    _authorize(logged_in_client)
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "scope": DRIVE}))
    assert _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state")).headers["location"] == (
        "/#/essays?connected=1"
    )
    assert gmail_profile.tokens == []
    assert [a.email for a in _accounts(db_session)] == ["me@gmail.com"]
    settings = logged_in_client.get("/api/settings").json()
    assert settings["gmail_granted"] is True and settings["google_connected"] is True


def test_gmail_marker_cannot_bypass_state_check(logged_in_client, monkeypatch):
    _authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    response = _callback(logged_in_client, "gmail." + state)
    assert response.status_code == 400
    assert calls == []


def test_cancelled_consent_stores_nothing_and_returns(logged_in_client, db_session, monkeypatch, gmail_profile):
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    logged_in_client.get("/api/docs/google/authorize?gmail=1", follow_redirects=False)
    response = _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state"), code=None)
    assert response.headers["location"] == "/#/settings?gmail=0"
    _authorize(logged_in_client)
    response = _callback(logged_in_client, logged_in_client.cookies.get("google_oauth_state"), code=None)
    assert response.headers["location"] == "/#/essays?connected=0"
    assert calls == [] and gmail_profile.tokens == []
    assert db_session.query(OAuthToken).count() == 0 and _accounts(db_session) == []


def test_cancelled_consent_still_checks_state(logged_in_client):
    _authorize(logged_in_client)
    assert _callback(logged_in_client, "wrong", code=None).status_code == 400


# Reconnect on an inbox carried over from Phase 6 (no address yet).


def _suggest(db_session, account, mid, state="pending"):
    from datetime import UTC, datetime

    from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind

    row = EmailSuggestion(
        gmail_account_id=account.id,
        gmail_message_id=mid,
        gmail_thread_id=f"t{mid}",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        direction=EmailDirection.INBOUND,
        kind=SuggestionKind.REJECTION,
        state=state,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _reconnect(client, monkeypatch, inbox_id, refresh="new"):
    response = client.get(f"/api/docs/google/authorize?gmail=1&inbox={inbox_id}", follow_redirects=False)
    assert response.status_code == 302
    state = client.cookies.get("google_oauth_state")
    assert state.startswith(f"gmail.{inbox_id}.")
    assert parse_qs(urlparse(response.headers["location"]).query)["state"] == [state]
    monkeypatch.setattr(httpx, "post", fake_post_returning({**TOKENS, "refresh_token": refresh, "scope": GMAIL}))
    return _callback(client, state)


def test_reconnect_gives_the_unaddressed_inbox_its_address(logged_in_client, db_session, monkeypatch, gmail_profile):
    carried = grant_gmail(db_session, None, refresh_token="broken")
    carried.history_cursor = "1760000000000"
    carried.last_error = "google token request rejected (status 400); reconnect this inbox in Settings"
    db_session.commit()
    kept = _suggest(db_session, carried, "m1", state="accepted")

    assert _reconnect(logged_in_client, monkeypatch, carried.id).headers["location"] == "/#/settings?gmail=1"

    (account,) = _accounts(db_session)
    assert account.id == carried.id and account.email == "me@gmail.com"
    assert decrypt_value(account.encrypted_refresh_token) == "new"
    assert account.history_cursor == "1760000000000" and account.last_error is None
    assert db_session.get(type(kept), kept.id).gmail_account_id == carried.id


def test_reconnect_merges_the_unaddressed_inbox_into_one_with_its_address(
    logged_in_client, db_session, monkeypatch, gmail_profile
):
    carried = grant_gmail(db_session, None, refresh_token="broken")
    again = grant_gmail(db_session, "me@gmail.com", refresh_token="older")
    only_old = _suggest(db_session, carried, "m1", state="accepted")
    _suggest(db_session, carried, "m2")
    both = _suggest(db_session, again, "m2")
    carried_id = carried.id

    assert _reconnect(logged_in_client, monkeypatch, carried_id).headers["location"] == "/#/settings?gmail=1"

    (account,) = _accounts(db_session)
    assert account.id == again.id and decrypt_value(account.encrypted_refresh_token) == "new"
    rows = db_session.query(type(both)).order_by(type(both).id).all()
    assert [(r.id, r.gmail_account_id, r.gmail_message_id) for r in rows] == [
        (only_old.id, again.id, "m1"),
        (both.id, again.id, "m2"),
    ]
    assert db_session.get(GmailAccount, carried_id) is None


def test_reconnect_naming_an_addressed_or_unknown_inbox_is_a_plain_connect(
    logged_in_client, db_session, monkeypatch, gmail_profile
):
    school = grant_gmail(db_session, "me@school.edu", refresh_token="school")
    gmail_profile.address = "me@gmail.com"
    for inbox_id in (school.id, 999999):
        assert _reconnect(logged_in_client, monkeypatch, inbox_id).status_code == 302
    accounts = _accounts(db_session)
    assert [a.email for a in accounts] == ["me@school.edu", "me@gmail.com"]
    assert decrypt_value(accounts[0].encrypted_refresh_token) == "school"


@pytest.mark.parametrize("inbox", ["0", "-1", "x", "1.5"])
def test_authorize_refuses_a_bad_inbox_id(logged_in_client, inbox):
    assert logged_in_client.get(f"/api/docs/google/authorize?gmail=1&inbox={inbox}", follow_redirects=False).status_code == 422


def test_an_inbox_id_cannot_be_slipped_into_the_state(logged_in_client, db_session, monkeypatch):
    carried = grant_gmail(db_session, None)
    _gmail_authorize(logged_in_client)
    state = logged_in_client.cookies.get("google_oauth_state")
    calls = []
    monkeypatch.setattr(httpx, "post", fake_post_returning(TOKENS, calls=calls))
    forged = state.replace("gmail.", f"gmail.{carried.id}.", 1)
    assert _callback(logged_in_client, forged).status_code == 400
    assert calls == []
