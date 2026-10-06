from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_value, encrypt_value
from app.models.oauth_token import OAuthToken
from app.services.errors import GoogleAuthError

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_PROVIDER = "google"
_HTTP_TIMEOUT = 10.0


def get_authorization_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",  # offline + consent so Google returns a refresh_token
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _post_token_request(data: dict) -> dict:
    """POST to Google's token endpoint. Errors never include response bodies
    or token values."""
    try:
        response = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise GoogleAuthError(f"google token request failed ({type(exc).__name__})") from None
    if not response.is_success:
        raise GoogleAuthError(f"google token request rejected (status {response.status_code})")
    try:
        return response.json()
    except ValueError:
        raise GoogleAuthError("google token response was not valid json") from None


def exchange_code_for_token(code: str) -> dict:
    return _post_token_request(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    )


def _get_token_row(db: Session) -> OAuthToken | None:
    return db.scalars(select(OAuthToken).where(OAuthToken.provider == GOOGLE_PROVIDER)).first()


def store_token(db: Session, token_response: dict, scopes: str) -> None:
    """Upsert the single google row. Keeps the existing refresh token when the
    response has none (Google only sends one on first consent)."""
    row = _get_token_row(db)
    refresh_token = token_response.get("refresh_token")
    if not refresh_token and row is None:
        raise GoogleAuthError("google did not return a refresh token")
    if row is None:
        row = OAuthToken(provider=GOOGLE_PROVIDER)
        db.add(row)
    if refresh_token:
        row.encrypted_refresh_token = encrypt_value(refresh_token)
    row.scopes = scopes
    db.commit()


def get_valid_access_token(db: Session) -> str:
    row = _get_token_row(db)
    if row is None:
        raise GoogleAuthError("google is not connected")
    data = _post_token_request(
        {
            "refresh_token": decrypt_value(row.encrypted_refresh_token),
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        }
    )
    access_token = data.get("access_token")
    if not access_token:
        raise GoogleAuthError("google did not return an access token")
    return access_token
