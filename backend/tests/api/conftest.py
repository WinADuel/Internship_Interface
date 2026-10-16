from contextlib import nullcontext

import httpx
import pytest

from app.api.deps import (
    get_discovery_http,
    get_gmail_client_factory,
    get_gmail_token_client_factory,
    get_scan_session_factory,
)
from app.core.config import settings
from app.main import app
from app.services.gmail.client import GoogleGmailClient
from tests.credentials import seed_credential
from tests.services.discovery.fakes import FakeDiscoveryHttp


@pytest.fixture()
def seeded_credential(db_session):
    return seed_credential(db_session, with_totp=True, confirmed=True)


@pytest.fixture()
def seeded_credential_confirmed(seeded_credential):
    return seeded_credential


@pytest.fixture()
def seeded_credential_unconfirmed(db_session):
    return seed_credential(db_session, with_totp=True, confirmed=False)


@pytest.fixture()
def logged_in_client(client, seeded_credential):
    response = client.post(
        "/api/auth/login",
        json={
            "username": "dxwu",
            "password": "correct-horse",
            "totp_code": seeded_credential.current_totp_code(),
        },
    )
    assert response.status_code == 200
    return client


@pytest.fixture(autouse=True)
def insecure_cookies(monkeypatch):
    """TestClient talks to http://testserver, where Secure cookies would not
    round-trip; tests that care about Secure set it back to True themselves."""
    monkeypatch.setattr(settings, "cookie_secure", False)


@pytest.fixture(autouse=True)
def discovery_http():
    """Every discovery route gets this fake instead of real HTTP, so no API
    test touches the network; tests script its responses."""
    fake = FakeDiscoveryHttp()
    app.dependency_overrides[get_discovery_http] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_discovery_http, None)


@pytest.fixture(autouse=True)
def scan_in_test_session(db_session):
    """Scan now's background task opens "its own" session; here that is the
    test session (left open on exit), so the scan sees the test's data and
    its commits stay inside the test transaction."""
    app.dependency_overrides[get_scan_session_factory] = lambda: lambda: nullcontext(db_session)
    yield
    app.dependency_overrides.pop(get_scan_session_factory, None)


class FakeGmailProfile:
    """Gmail's profile endpoint for the Connect Gmail callback, on
    httpx.MockTransport: answers `address` (or `status`), records each
    request's access token, and refuses every other Gmail call."""

    def __init__(self, address: str = "me@gmail.com", status: int = 200):
        self.address = address
        self.status = status
        self.tokens: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.tokens.append(request.headers.get("authorization", ""))
        if not request.url.path.endswith("/users/me/profile"):
            return httpx.Response(404)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "secret body text"}})
        return httpx.Response(200, json={"emailAddress": self.address, "messagesTotal": 1})

    def factory(self, access_token: str) -> GoogleGmailClient:
        return GoogleGmailClient(access_token, transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def gmail_profile():
    """No API test reaches Gmail: the callback's profile lookup gets this
    fake, and Sync now fails loudly unless a test supplies a fake inbox."""
    fake = FakeGmailProfile()

    def no_real_gmail(db, account):
        raise AssertionError("tests must give Sync now a fake Gmail client")

    app.dependency_overrides[get_gmail_token_client_factory] = lambda: fake.factory
    app.dependency_overrides[get_gmail_client_factory] = lambda: no_real_gmail
    yield fake
    app.dependency_overrides.pop(get_gmail_token_client_factory, None)
    app.dependency_overrides.pop(get_gmail_client_factory, None)
