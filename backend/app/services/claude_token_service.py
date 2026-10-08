"""Revocable bearer tokens for the scheduled Claude job (spec §13.5).
Only the SHA-256 hash is stored; the plaintext is returned once."""

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.claude_token import ClaudeToken
from app.services.errors import ClaudeTokenNotFoundError

TOKEN_PREFIX = "ct_"
DISPLAY_PREFIX_LENGTH = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(db: Session) -> tuple[ClaudeToken, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ClaudeToken(token_hash=_hash(raw), token_prefix=raw[:DISPLAY_PREFIX_LENGTH], created_at=_now())
    db.add(token)
    db.commit()
    return token, raw


def authenticate(db: Session, raw: str, now: datetime | None = None) -> ClaudeToken | None:
    if not raw:
        return None
    token = db.scalars(select(ClaudeToken).where(ClaudeToken.token_hash == _hash(raw))).first()
    if token is None or token.revoked_at is not None:
        return None
    token.last_used_at = now or _now()
    db.commit()
    return token


def list_tokens(db: Session) -> list[ClaudeToken]:
    return list(db.scalars(select(ClaudeToken).order_by(ClaudeToken.created_at.desc(), ClaudeToken.id.desc())))


def revoke_token(db: Session, token_id: int, now: datetime | None = None) -> ClaudeToken:
    token = db.get(ClaudeToken, token_id)
    if token is None:
        raise ClaudeTokenNotFoundError(token_id)
    if token.revoked_at is None:
        token.revoked_at = now or _now()
        db.commit()
    return token
