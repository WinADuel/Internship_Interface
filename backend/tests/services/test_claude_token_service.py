import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.claude_token import ClaudeToken
from app.services.claude_token_service import TOKEN_PREFIX, authenticate, create_token, list_tokens, revoke_token
from app.services.errors import ClaudeTokenNotFoundError

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_plaintext_is_never_stored(db_session):
    token, raw = create_token(db_session)
    assert raw.startswith(TOKEN_PREFIX) and len(raw) > 40
    assert token.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert token.token_prefix == raw[:8]
    row = db_session.scalars(select(ClaudeToken).where(ClaudeToken.id == token.id)).one()
    for column in ClaudeToken.__table__.columns:
        assert getattr(row, column.key) != raw


def test_authenticate_accepts_plaintext_and_stamps_last_used(db_session):
    token, raw = create_token(db_session)
    assert authenticate(db_session, raw, now=NOW) is token
    assert token.last_used_at == NOW


def test_authenticate_rejects_wrong_and_revoked(db_session):
    token, raw = create_token(db_session)
    assert authenticate(db_session, raw + "x") is None
    assert authenticate(db_session, "") is None
    revoke_token(db_session, token.id, now=NOW)
    assert token.revoked_at == NOW
    assert authenticate(db_session, raw) is None


def test_revoke_is_idempotent_and_unknown_raises(db_session):
    token, _ = create_token(db_session)
    revoke_token(db_session, token.id, now=NOW)
    revoke_token(db_session, token.id, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert token.revoked_at == NOW
    with pytest.raises(ClaudeTokenNotFoundError):
        revoke_token(db_session, 999999)


def test_list_tokens_newest_first(db_session):
    a, _ = create_token(db_session)
    b, _ = create_token(db_session)
    assert [t.id for t in list_tokens(db_session)][:2] == [b.id, a.id]
