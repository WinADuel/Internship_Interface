from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32
_JWT_PLACEHOLDERS = frozenset({"change-me", "changeme", "secret"})


class Settings(BaseSettings):
    """Application configuration, read from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str
    jwt_secret: str
    token_encryption_key: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    cookie_secure: bool = True

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_is_strong(cls, value: str) -> str:
        how = 'generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        if value.strip().lower() in _JWT_PLACEHOLDERS:
            raise ValueError(f"JWT_SECRET is still a placeholder; {how}")
        if len(value.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes; {how}")
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def _token_encryption_key_is_fernet(cls, value: str) -> str:
        try:
            Fernet(value)
        except (ValueError, TypeError):
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded "
                "bytes); generate one with: python -c "
                '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        return value


settings = Settings()
