from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    decrypt_value,
    encrypt_value,
    generate_totp_secret,
    hash_password,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)
from app.models.auth_credential import AuthCredential
from app.services.errors import (
    InvalidCredentialsError,
    InvalidTotpCodeError,
    TotpAlreadyConfirmedError,
)

# Verified against when the username is unknown, so a miss costs the same bcrypt
# work as a hit and usernames cannot be enumerated by timing.
_DUMMY_HASH = hash_password("dummy-password")


def _get_credential(db: Session) -> AuthCredential:
    """Return the single account's credential row (this app is single-user)."""
    credential = db.scalars(select(AuthCredential).order_by(AuthCredential.id)).first()
    if credential is None:
        raise InvalidCredentialsError()
    return credential


def authenticate(db: Session, username: str, password: str, totp_code: str) -> None:
    """Verify username, password and (when confirmed) TOTP code.

    Raises `InvalidCredentialsError` on any failure, without revealing which.
    """
    credential = db.scalars(
        select(AuthCredential).where(AuthCredential.username == username)
    ).first()
    password_hash = credential.password_hash if credential else _DUMMY_HASH
    try:
        password_ok = verify_password(password, password_hash)
    except ValueError:  # malformed stored hash: an auth failure, not a 500
        password_ok = False
    if credential is None or not password_ok:
        raise InvalidCredentialsError()

    if credential.totp_confirmed:
        if not totp_code or credential.totp_secret_encrypted is None:
            raise InvalidCredentialsError()
        secret = decrypt_value(credential.totp_secret_encrypted)
        if not verify_totp_code(secret, totp_code):
            raise InvalidCredentialsError()


def begin_totp_setup(db: Session) -> tuple[str, str]:
    """Generate and store a fresh unconfirmed TOTP secret.

    Returns `(secret, provisioning_uri)`. Raises `TotpAlreadyConfirmedError`
    if 2FA is already confirmed.
    """
    credential = _get_credential(db)
    if credential.totp_confirmed:
        raise TotpAlreadyConfirmedError()
    secret = generate_totp_secret()
    credential.totp_secret_encrypted = encrypt_value(secret)
    db.commit()
    return secret, totp_provisioning_uri(secret, credential.username)


def confirm_totp_setup(db: Session, code: str) -> None:
    """Confirm the pending TOTP secret with a code from the authenticator app."""
    credential = _get_credential(db)
    if credential.totp_secret_encrypted is None:
        raise InvalidTotpCodeError()
    secret = decrypt_value(credential.totp_secret_encrypted)
    if not verify_totp_code(secret, code):
        raise InvalidTotpCodeError()
    credential.totp_confirmed = True
    db.commit()
