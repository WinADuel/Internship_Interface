from contextlib import nullcontext

import pytest

from app.api.deps import get_discovery_http, get_scan_session_factory
from app.core.config import settings
from app.main import app
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
