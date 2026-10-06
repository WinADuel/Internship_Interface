"""First-time account bootstrap: create (or reset) the single user and confirm TOTP.

Pure logic, no prompts or printing, so it can be tested directly. Callers own
the transaction: these functions flush but never commit.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    encrypt_value,
    generate_totp_secret,
    hash_password,
    verify_totp_code,
)
from app.models.auth_credential import AuthCredential

MIN_PASSWORD_LENGTH = 12


class AccountExistsError(Exception):
    """An account already exists and reset was not requested."""


def create_or_reset_user(
    db: Session, username: str, password: str, *, reset: bool
) -> tuple[AuthCredential, str]:
    """Create the single account, or with `reset=True` replace the existing one in place.

    Returns the credential (unconfirmed TOTP) and the new plaintext TOTP secret.
    """
    username = username.strip()
    if not username:
        raise ValueError("username must not be empty")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")

    existing = db.scalars(select(AuthCredential).order_by(AuthCredential.id)).first()
    if existing is not None and not reset:
        raise AccountExistsError(
            "an account already exists; use --reset to replace its password and authenticator"
        )

    secret = generate_totp_secret()
    credential = existing if existing is not None else AuthCredential()
    credential.username = username
    credential.password_hash = hash_password(password)
    credential.totp_secret_encrypted = encrypt_value(secret)
    credential.totp_confirmed = False
    if existing is None:
        db.add(credential)
    db.flush()
    return credential, secret


def confirm_enrollment(db: Session, credential: AuthCredential, secret: str, code: str) -> bool:
    """Mark TOTP confirmed only if `code` is valid for `secret`."""
    if not verify_totp_code(secret, code):
        return False
    credential.totp_confirmed = True
    db.flush()
    return True
