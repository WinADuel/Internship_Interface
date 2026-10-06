"""Shared helpers for seeding an `AuthCredential` row in tests."""

import pyotp

from app.core.security import encrypt_value, generate_totp_secret, hash_password
from app.models.auth_credential import AuthCredential

USERNAME = "dxwu"
PASSWORD = "correct-horse"


class SeededCredential:
    """An inserted `AuthCredential` plus its plaintext TOTP secret."""

    def __init__(self, row: AuthCredential, secret: str | None):
        self.row = row
        self.secret = secret

    def current_totp_code(self) -> str:
        return pyotp.TOTP(self.secret).now()


def seed_credential(db_session, *, with_totp: bool, confirmed: bool) -> SeededCredential:
    secret = generate_totp_secret() if with_totp else None
    row = AuthCredential(
        username=USERNAME,
        password_hash=hash_password(PASSWORD),
        totp_secret_encrypted=encrypt_value(secret) if secret else None,
        totp_confirmed=confirmed,
    )
    db_session.add(row)
    db_session.commit()
    return SeededCredential(row, secret)
