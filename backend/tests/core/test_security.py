from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_value,
    encrypt_value,
    generate_totp_secret,
    hash_password,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse")
    assert hashed != "correct-horse"
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong", hashed)


def test_totp_roundtrip():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret, code)
    assert not verify_totp_code(secret, "000000")


def test_totp_provisioning_uri_contains_username_and_issuer():
    secret = generate_totp_secret()
    uri = totp_provisioning_uri(secret, "alice", issuer="InternHelper")
    assert uri.startswith("otpauth://totp/")
    assert "alice" in uri
    assert "InternHelper" in uri


def test_encrypt_decrypt_roundtrip():
    ciphertext = encrypt_value("my-refresh-token")
    assert ciphertext != b"my-refresh-token"
    assert decrypt_value(ciphertext) == "my-refresh-token"


def test_access_token_roundtrip():
    token = create_access_token(subject="1")
    payload = decode_token(token)
    assert payload["sub"] == "1"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    token = create_refresh_token(subject="1")
    payload = decode_token(token)
    assert payload["sub"] == "1"
    assert payload["type"] == "refresh"


def test_decode_token_rejects_wrong_expected_type():
    access = create_access_token(subject="1")
    refresh = create_refresh_token(subject="1")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(access, expected_type="refresh")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, expected_type="access")


def test_decode_token_accepts_matching_expected_type():
    assert decode_token(create_access_token("1"), expected_type="access")["type"] == "access"
    assert decode_token(create_refresh_token("1"), expected_type="refresh")["type"] == "refresh"


def _sign(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def test_decode_token_rejects_missing_exp():
    token = _sign({"sub": "1", "type": "access", "iat": datetime.now(timezone.utc)})
    with pytest.raises(jwt.PyJWTError):
        decode_token(token)


def test_decode_token_rejects_expired_token():
    now = datetime.now(timezone.utc)
    token = _sign(
        {"sub": "1", "type": "access", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)}
    )
    with pytest.raises(jwt.PyJWTError):
        decode_token(token)


def test_decode_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_token("not-a-real-token")
