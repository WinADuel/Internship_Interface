import jwt
import pyotp
import pytest

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


def test_access_and_refresh_tokens_are_not_interchangeable():
    access = create_access_token(subject="1")
    refresh = create_refresh_token(subject="1")
    assert decode_token(access)["type"] != decode_token(refresh)["type"]


def test_decode_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_token("not-a-real-token")
