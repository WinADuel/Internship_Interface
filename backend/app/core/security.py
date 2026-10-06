"""Security primitives: password hashing, TOTP, symmetric encryption, and JWTs.

Each helper wraps a single well-vetted library primitive rather than rolling
any crypto logic of its own:
- passlib's bcrypt handler for password hashing/verification.
- pyotp for RFC 6238 TOTP generation/verification (Google Authenticator compatible).
- cryptography.fernet.Fernet for generic symmetric encryption of secrets at rest.
- PyJWT (HS256) for access/refresh token issuance and verification.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pyotp
from cryptography.fernet import Fernet
from passlib.hash import bcrypt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
_JWT_ALGORITHM = "HS256"


# -- Password hashing --------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.verify(password, password_hash)


# -- TOTP (RFC 6238) ----------------------------------------------------------


def generate_totp_secret() -> str:
    """Generate a new random base32 TOTP secret."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str, issuer: str = "InternHelper") -> str:
    """Build an `otpauth://` URI for provisioning an authenticator app (e.g. as a QR code)."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp_code(secret: str, code: str) -> bool:
    """Check a 6-digit TOTP code against the secret, allowing normal clock drift."""
    return pyotp.TOTP(secret).verify(code)


# -- Generic symmetric encryption (Fernet) ------------------------------------


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key)


def encrypt_value(plaintext: str) -> bytes:
    """Encrypt a string for storage at rest. Generic helper, not tied to any one use case."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_value(ciphertext: bytes) -> str:
    """Decrypt a value previously produced by `encrypt_value`."""
    return _fernet().decrypt(ciphertext).decode("utf-8")


# -- JWTs ----------------------------------------------------------------------


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    """Issue a short-lived access token encoding `type: "access"`."""
    return _create_token(
        subject,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(subject: str) -> str:
    """Issue a long-lived refresh token encoding `type: "refresh"`."""
    return _create_token(
        subject,
        REFRESH_TOKEN_TYPE,
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    """Decode and verify a JWT, returning its payload.

    Requires the `exp`, `iat`, `sub` and `type` claims. If `expected_type` is
    given, the token's `type` claim must match it (so access and refresh tokens
    cannot be swapped).

    Raises `jwt.PyJWTError` (or a subclass, e.g. `ExpiredSignatureError`,
    `InvalidTokenError`) if the token is malformed, expired, missing a required
    claim, has a bad signature, or has the wrong type.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[_JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if expected_type is not None and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected token type {expected_type!r}")
    return payload
