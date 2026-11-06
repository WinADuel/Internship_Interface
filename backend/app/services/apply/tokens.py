"""Revocable bearer tokens for the Chrome extension. Only the SHA-256 hash
is stored; the plaintext is returned once. Separate from the Claude job's
tokens, so neither can reach the other's routes."""

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.apply import ExtensionToken
from app.services.errors import ExtensionTokenNotFoundError

TOKEN_PREFIX = "ih_"
DISPLAY_PREFIX_LENGTH = 8


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(db: Session) -> tuple[ExtensionToken, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ExtensionToken(token_hash=_hash(raw), token_prefix=raw[:DISPLAY_PREFIX_LENGTH], created_at=utc_now())
    db.add(token)
    db.commit()
    return token, raw


def authenticate(db: Session, raw: str, now: datetime | None = None) -> ExtensionToken | None:
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    token = db.scalars(select(ExtensionToken).where(ExtensionToken.token_hash == _hash(raw))).first()
    if token is None or token.revoked_at is not None:
        return None
    token.last_used_at = now or utc_now()
    db.commit()
    return token


def list_tokens(db: Session) -> list[ExtensionToken]:
    return list(
        db.scalars(select(ExtensionToken).order_by(ExtensionToken.created_at.desc(), ExtensionToken.id.desc()))
    )


def revoke_token(db: Session, token_id: int, now: datetime | None = None) -> ExtensionToken:
    token = db.get(ExtensionToken, token_id)
    if token is None:
        raise ExtensionTokenNotFoundError(token_id)
    if token.revoked_at is None:
        token.revoked_at = now or utc_now()
        db.commit()
    return token
