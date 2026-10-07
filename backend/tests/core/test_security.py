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
    match_totp_step,
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


def test_verify_totp_code_accepts_previous_step():
    """Verify that codes from the previous 30-second step are accepted."""
    secret = generate_totp_secret()
    now = datetime.now(timezone.utc)
    # Generate code for 30 seconds ago (previous step)
    previous_step_code = pyotp.TOTP(secret).at(now - timedelta(seconds=30))
    # Verify it's accepted
    assert verify_totp_code(secret, previous_step_code)


def test_verify_totp_code_rejects_code_two_steps_old():
    """Verify that codes from two steps ago (90 seconds old) are rejected."""
    secret = generate_totp_secret()
    now = datetime.now(timezone.utc)
    # Generate code for 90 seconds ago (two steps back)
    two_steps_old_code = pyotp.TOTP(secret).at(now - timedelta(seconds=90))
    # Verify it's rejected
    assert not verify_totp_code(secret, two_steps_old_code)


# -- match_totp_step (replay-guard support) ---------------------------------


def _step_of(timestamp: float) -> int:
    return int(timestamp) // 30


def test_match_totp_step_returns_current_step():
    secret = generate_totp_secret()
    now = 1_800_000_000
    code = pyotp.TOTP(secret).at(now)
    assert match_totp_step(secret, code, now=now) == _step_of(now)


def test_match_totp_step_accepts_adjacent_steps_and_reports_them():
    secret = generate_totp_secret()
    now = 1_800_000_000
    totp = pyotp.TOTP(secret)
    assert match_totp_step(secret, totp.at(now - 30), now=now) == _step_of(now) - 1
    assert match_totp_step(secret, totp.at(now + 30), now=now) == _step_of(now) + 1


def test_match_totp_step_rejects_codes_two_steps_away():
    secret = generate_totp_secret()
    now = 1_800_000_000
    totp = pyotp.TOTP(secret)
    assert match_totp_step(secret, totp.at(now - 60), now=now) is None
    assert match_totp_step(secret, totp.at(now + 60), now=now) is None


def test_match_totp_step_rejects_wrong_or_empty_code():
    secret = generate_totp_secret()
    assert match_totp_step(secret, "", now=1_800_000_000) is None
    assert match_totp_step(secret, "abcdef", now=1_800_000_000) is None
    assert match_totp_step(secret, "12345é", now=1_800_000_000) is None


def test_match_totp_step_defaults_to_the_real_clock():
    secret = generate_totp_secret()
    assert match_totp_step(secret, pyotp.TOTP(secret).now()) is not None
