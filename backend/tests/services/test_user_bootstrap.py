import pyotp
import pytest
from sqlalchemy import func, select

from app.core.security import decrypt_value, verify_password
from app.models.auth_credential import AuthCredential
from app.services.user_bootstrap import (
    AccountExistsError,
    confirm_enrollment,
    create_or_reset_user,
)

PASSWORD = "correct-horse-battery"


def _count(db):
    return db.scalar(select(func.count()).select_from(AuthCredential))


def test_creates_hashed_unconfirmed_credential(db_session):
    cred, secret = create_or_reset_user(db_session, "me", PASSWORD, reset=False)
    assert cred.password_hash != PASSWORD
    assert verify_password(PASSWORD, cred.password_hash)
    assert cred.totp_secret_encrypted != secret.encode()
    assert decrypt_value(cred.totp_secret_encrypted) == secret
    assert cred.totp_confirmed is False


def test_short_password_rejected(db_session):
    with pytest.raises(ValueError):
        create_or_reset_user(db_session, "me", "short", reset=False)
    assert _count(db_session) == 0


def test_existing_account_without_reset_errors(db_session):
    create_or_reset_user(db_session, "me", PASSWORD, reset=False)
    with pytest.raises(AccountExistsError, match="use --reset"):
        create_or_reset_user(db_session, "other", PASSWORD, reset=False)
    assert _count(db_session) == 1


def test_reset_replaces_in_place(db_session):
    first, _ = create_or_reset_user(db_session, "me", PASSWORD, reset=False)
    new_password = "another-long-password"
    second, _ = create_or_reset_user(db_session, "me2", new_password, reset=True)
    assert _count(db_session) == 1
    assert second.id == first.id
    assert second.username == "me2"
    assert verify_password(new_password, second.password_hash)
    assert not verify_password(PASSWORD, second.password_hash)
    assert second.totp_confirmed is False


def test_confirm_enrollment_valid_code(db_session):
    cred, secret = create_or_reset_user(db_session, "me", PASSWORD, reset=False)
    assert confirm_enrollment(db_session, cred, secret, pyotp.TOTP(secret).now()) is True
    assert cred.totp_confirmed is True


def test_confirm_enrollment_wrong_code(db_session):
    cred, secret = create_or_reset_user(db_session, "me", PASSWORD, reset=False)
    good = pyotp.TOTP(secret).now()
    bad = f"{(int(good) + 500000) % 1000000:06d}"
    assert confirm_enrollment(db_session, cred, secret, bad) is False
    assert cred.totp_confirmed is False


@pytest.mark.parametrize("username", ["", "   "])
def test_empty_username_rejected(db_session, username):
    with pytest.raises(ValueError, match="username must not be empty"):
        create_or_reset_user(db_session, username, PASSWORD, reset=False)
    assert _count(db_session) == 0


def test_username_is_stripped(db_session):
    cred, _ = create_or_reset_user(db_session, " dxwu ", PASSWORD, reset=False)
    assert cred.username == "dxwu"
