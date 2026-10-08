import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings

GOOD_JWT = "a" * 32 + "-test-only-jwt-secret"


def _make(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+psycopg://app:app@localhost:5432/x",
        "jwt_secret": GOOD_JWT,
        "token_encryption_key": Fernet.generate_key().decode(),
        "google_client_id": "id",
        "google_client_secret": "secret",
        "google_redirect_uri": "http://localhost/cb",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_settings_load():
    assert _make().jwt_secret == GOOD_JWT


def test_jwt_secret_exactly_32_bytes_is_accepted():
    assert _make(jwt_secret="x" * 32).jwt_secret == "x" * 32


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_jwt_secret_shorter_than_32_bytes_is_rejected(secret):
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        _make(jwt_secret=secret)


def test_jwt_secret_length_is_counted_in_bytes_not_characters():
    # 16 two-byte characters is 32 bytes (accepted); 15 is 30 bytes (rejected).
    assert _make(jwt_secret="é" * 16)
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        _make(jwt_secret="é" * 15)


@pytest.mark.parametrize("placeholder", ["change-me", "changeme", "secret", "Change-Me", " SECRET "])
def test_jwt_secret_placeholders_are_rejected(placeholder):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _make(jwt_secret=placeholder)


def test_jwt_secret_error_names_how_to_generate_one():
    with pytest.raises(ValidationError, match="secrets.token_urlsafe"):
        _make(jwt_secret="change-me")


@pytest.mark.parametrize("key", ["change-me", "", "not-base64!!", "dG9vLXNob3J0"])
def test_invalid_fernet_key_is_rejected(key):
    with pytest.raises(ValidationError, match="TOKEN_ENCRYPTION_KEY"):
        _make(token_encryption_key=key)


def test_fernet_error_names_how_to_generate_one():
    with pytest.raises(ValidationError, match="Fernet.generate_key"):
        _make(token_encryption_key="change-me")


def test_validation_errors_do_not_echo_the_secret_value():
    with pytest.raises(ValidationError) as excinfo:
        _make(jwt_secret="hunter2-too-short")
    assert "hunter2-too-short" not in str(excinfo.value)


def test_backup_settings_are_optional_with_defaults():
    s = _make()
    assert s.backup_dir == "/backups"
    assert s.backup_encryption_key is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_backup_encryption_key_means_unset(blank):
    assert _make(backup_encryption_key=blank).backup_encryption_key is None


def test_valid_backup_encryption_key_is_accepted():
    key = Fernet.generate_key().decode()
    assert _make(backup_encryption_key=key).backup_encryption_key == key


@pytest.mark.parametrize("key", ["change-me", "not-base64!!", "dG9vLXNob3J0"])
def test_invalid_backup_encryption_key_is_rejected_without_echoing_it(key):
    with pytest.raises(ValidationError, match="BACKUP_ENCRYPTION_KEY") as excinfo:
        _make(backup_encryption_key=key)
    assert "Fernet.generate_key" in str(excinfo.value)
    assert key not in str(excinfo.value)
