import re
from urllib.parse import urlencode

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_value, encrypt_value
from app.models.oauth_token import OAuthToken
from app.services.errors import (
    GoogleAuthError,
    GoogleDocsFetchError,
    GoogleNotConnectedError,
    InvalidDocRefError,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Read-only Docs access plus drive.file, which reaches only files this app
# creates (the backup sheet, spec §13.7). No other write scope, ever.
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
)
GOOGLE_SCOPE = " ".join(GOOGLE_SCOPES)
# Gmail sync (Phase 6 spec §2) is a separate, optional consent on top of the
# scopes above. gmail.readonly is read-only: the app cannot send, delete or
# label mail. It is requested only by Connect Gmail, never by default.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_PROVIDER = "google"
_HTTP_TIMEOUT = 10.0
_FETCH_TIMEOUT = 15.0
GOOGLE_EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{doc_id}/export"
_DOC_URL_RE = re.compile(r"^https://docs\.google\.com/document/d/([^/?#]+)(?:[/?#].*)?$")
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def requested_scope(gmail: bool = False) -> str:
    """The space-separated scopes an authorization request asks for."""
    return f"{GOOGLE_SCOPE} {GMAIL_SCOPE}" if gmail else GOOGLE_SCOPE


def get_authorization_url(state: str, gmail: bool = False) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "scope": requested_scope(gmail),
        "access_type": "offline",  # offline + consent so Google returns a refresh_token
        "prompt": "consent",
        "state": state,
    }
    if gmail:
        # Incremental authorization: the new token keeps the scopes already granted.
        params["include_granted_scopes"] = "true"
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def granted_scopes(token_response: dict, requested: str) -> str:
    """The scopes Google actually granted (the token response's `scope`),
    falling back to what was requested when the field is absent or blank."""
    scope = token_response.get("scope")
    if isinstance(scope, str) and scope.split():
        return " ".join(scope.split())
    return requested


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


def is_google_connected(db: Session) -> bool:
    """Whether a Google connection is stored (it may still have been revoked)."""
    return _get_token_row(db) is not None


def is_gmail_granted(db: Session) -> bool:
    """Whether the stored Google connection includes the Gmail read scope."""
    row = _get_token_row(db)
    return row is not None and GMAIL_SCOPE in row.scopes.split()


def get_valid_access_token(db: Session) -> str:
    row = _get_token_row(db)
    if row is None:
        raise GoogleAuthError("google is not connected")
    try:
        refresh_token = decrypt_value(row.encrypted_refresh_token)
    except InvalidToken:
        raise GoogleAuthError("stored google token could not be decrypted") from None
    data = _post_token_request(
        {
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        }
    )
    access_token = data.get("access_token")
    if not access_token:
        raise GoogleAuthError("google did not return an access token")
    return access_token


def extract_doc_id(doc_ref: str) -> str:
    """Normalize a bare Drive file id or a docs.google.com document URL to the
    bare id, validating it so nothing unexpected reaches the request path."""
    ref = doc_ref.strip()
    match = _DOC_URL_RE.match(ref)
    doc_id = match.group(1) if match else ref
    if not _DOC_ID_RE.fullmatch(doc_id):
        raise InvalidDocRefError("invalid doc reference")
    return doc_id


def fetch_doc_text(db: Session, doc_ref: str) -> str:
    """Export a Google Doc as plain text. Errors never include response bodies
    or token values."""
    doc_id = extract_doc_id(doc_ref)
    if _get_token_row(db) is None:
        raise GoogleNotConnectedError("google is not connected")
    access_token = get_valid_access_token(db)
    try:
        response = httpx.get(
            GOOGLE_EXPORT_URL.format(doc_id=doc_id),
            params={"mimeType": "text/plain"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_FETCH_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GoogleDocsFetchError(f"google doc request failed ({type(exc).__name__})") from None
    if not response.is_success:
        raise GoogleDocsFetchError(f"google doc request rejected (status {response.status_code})")
    return response.text
