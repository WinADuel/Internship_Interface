import pytest

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
