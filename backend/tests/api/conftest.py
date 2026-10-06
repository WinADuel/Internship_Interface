import pytest
from app.core.config import settings

from tests.credentials import seed_credential


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
