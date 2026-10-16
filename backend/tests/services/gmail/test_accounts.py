"""Connected inboxes (Phase 7 spec §4): races with a sync learning an
address at the same moment."""

from sqlalchemy import select

from app.core.security import decrypt_value
from app.models.gmail_account import GmailAccount
from app.services.gmail import accounts
from app.services.google_docs_service import GMAIL_SCOPE
from tests.services.gmail.fakes import grant_gmail


def _late_lookup(monkeypatch):
    """`get_by_email` misses once, as if the address was taken right after
    the lookup (a sync learnt it for an inbox carried over from Phase 6)."""
    real = accounts.get_by_email
    calls = []

    def lookup(db, email):
        calls.append(email)
        return None if len(calls) == 1 else real(db, email)

    monkeypatch.setattr(accounts, "get_by_email", lookup)
    return calls


def test_upsert_updates_the_inbox_that_took_the_address_meanwhile(db_session, monkeypatch):
    existing = grant_gmail(db_session, "me@gmail.com", refresh_token="old")
    existing.last_error = "x"
    db_session.commit()
    calls = _late_lookup(monkeypatch)

    account = accounts.upsert_account(db_session, "me@gmail.com", {"refresh_token": "new"}, GMAIL_SCOPE)

    assert len(calls) == 2 and account.id == existing.id
    (row,) = db_session.scalars(select(GmailAccount)).all()
    assert decrypt_value(row.encrypted_refresh_token) == "new" and row.last_error is None


def test_reconnect_of_an_unaddressed_inbox_merges_when_the_address_was_taken_meanwhile(db_session, monkeypatch):
    carried = grant_gmail(db_session, None, refresh_token="broken")
    other = grant_gmail(db_session, "me@gmail.com", refresh_token="old")
    carried_id = carried.id
    _late_lookup(monkeypatch)

    account = accounts.reconnect_unaddressed(db_session, carried_id, "me@gmail.com", {"refresh_token": "new"}, GMAIL_SCOPE)

    assert account.id == other.id
    (row,) = db_session.scalars(select(GmailAccount)).all()
    assert row.id == other.id and decrypt_value(row.encrypted_refresh_token) == "new"
