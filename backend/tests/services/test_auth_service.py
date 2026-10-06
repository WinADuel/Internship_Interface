import pytest

from app.services.auth_service import authenticate, begin_totp_setup, confirm_totp_setup
from app.services.errors import (
    InvalidCredentialsError,
    InvalidTotpCodeError,
    TotpAlreadyConfirmedError,
)
from tests.credentials import seed_credential


def test_authenticate_succeeds_with_correct_credentials(db_session, seeded_credential):
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_authenticate_rejects_wrong_password(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "wrong", seeded_credential.current_totp_code())


def test_authenticate_rejects_unknown_username(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "nobody", "correct-horse", seeded_credential.current_totp_code())


def test_authenticate_rejects_wrong_totp(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", "000000")


def test_authenticate_rejects_malformed_password_hash(db_session, seeded_credential):
    seeded_credential.row.password_hash = "not-a-bcrypt-hash"
    db_session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_begin_totp_setup_rejects_when_already_confirmed(db_session, seeded_credential_confirmed):
    with pytest.raises(TotpAlreadyConfirmedError):
        begin_totp_setup(db_session)


def test_begin_totp_setup_returns_secret_and_uri(db_session):
    seed_credential(db_session, with_totp=False, confirmed=False)
    secret, uri = begin_totp_setup(db_session)
    assert uri.startswith("otpauth://totp/")
    assert secret in uri


def test_confirm_totp_setup_rejects_wrong_code(db_session, seeded_credential_unconfirmed):
    with pytest.raises(InvalidTotpCodeError):
        confirm_totp_setup(db_session, "000000")


def test_confirm_totp_setup_marks_confirmed(db_session, seeded_credential_unconfirmed):
    confirm_totp_setup(db_session, seeded_credential_unconfirmed.current_totp_code())
    db_session.refresh(seeded_credential_unconfirmed.row)
    assert seeded_credential_unconfirmed.row.totp_confirmed is True
