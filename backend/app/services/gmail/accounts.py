"""Connected Gmail inboxes (Phase 7 spec §4): add or reconnect one from a
Connect Gmail consent, list and remove them, and the access token for one.

Each inbox has its own refresh token, from a consent that asked for
gmail.readonly only, so adding or removing an inbox never touches the
Drive/Docs connection (`oauth_tokens`). Removing an inbox deletes its
email suggestions (ON DELETE CASCADE); nothing is revoked at Google."""

import logging

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import encrypt_value
from app.models.email_suggestion import EmailSuggestion
from app.models.gmail_account import GmailAccount
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import refresh_access_token
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

UNKNOWN_INBOX = "Gmail inbox"  # an inbox's label while its address is unknown
MAX_SUMMARY = 1000


def list_accounts(db: Session) -> list[GmailAccount]:
    """Every inbox, oldest first."""
    return list(db.scalars(select(GmailAccount).order_by(GmailAccount.created_at, GmailAccount.id)))


def get_by_email(db: Session, email: str) -> GmailAccount | None:
    return db.scalars(select(GmailAccount).where(GmailAccount.email == email)).first()


def _set_token(account: GmailAccount, token_response: dict, scopes: str) -> None:
    refresh_token = token_response.get("refresh_token")
    if refresh_token:
        account.encrypted_refresh_token = encrypt_value(refresh_token)
    account.scopes = scopes
    account.last_error = None


def upsert_account(db: Session, email: str, token_response: dict, scopes: str) -> GmailAccount:
    """Store a consent's token for the inbox `email` (already lower-cased):
    a new inbox is added; an existing one gets the new token and its error
    cleared (Reconnect). An existing inbox keeps its refresh token when the
    response has none. If the address was taken meanwhile (a sync just
    learnt it for an inbox carried over from Phase 6), that inbox is
    updated instead."""
    account = get_by_email(db, email)
    if account is None:
        if not token_response.get("refresh_token"):
            raise GoogleAuthError("google did not return a refresh token")
        account = GmailAccount(email=email)
        _set_token(account, token_response, scopes)
        db.add(account)
        try:
            db.commit()
            return account
        except IntegrityError:
            db.rollback()
            account = get_by_email(db, email)
            if account is None:
                raise
    _set_token(account, token_response, scopes)
    db.commit()
    return account


def merge_into(db: Session, source_id: int, target_id: int) -> None:
    """Move an inbox's suggestions to another inbox with the same address
    (those the target already holds are dropped) and remove the source row.
    The caller commits."""
    held = select(EmailSuggestion.gmail_message_id).where(EmailSuggestion.gmail_account_id == target_id)
    db.execute(
        delete(EmailSuggestion).where(
            EmailSuggestion.gmail_account_id == source_id, EmailSuggestion.gmail_message_id.in_(held)
        )
    )
    db.execute(
        update(EmailSuggestion).where(EmailSuggestion.gmail_account_id == source_id).values(gmail_account_id=target_id)
    )
    db.execute(delete(GmailAccount).where(GmailAccount.id == source_id))
    logger.info("gmail inbox %d has %d's address; merged into it", source_id, target_id)


def unaddressed(db: Session, account_id: int) -> GmailAccount | None:
    """The inbox `account_id` if it exists and has no address yet (carried
    over from Phase 6), else None."""
    account = db.get(GmailAccount, account_id)
    return account if account is not None and account.email is None else None


def reconnect_unaddressed(
    db: Session, account_id: int, email: str, token_response: dict, scopes: str
) -> GmailAccount:
    """Reconnect on an inbox without an address: it gets the address and
    the new token, keeping its cursor and suggestions. If the address
    already belongs to another inbox, that one gets the token and this
    row's suggestions, and this row goes. If the row has gained an address
    or gone meanwhile, it is a plain Connect Gmail."""
    account = unaddressed(db, account_id)
    if account is None:
        return upsert_account(db, email, token_response, scopes)
    other = get_by_email(db, email)
    if other is None:
        account.email = email
        _set_token(account, token_response, scopes)
        try:
            db.commit()
            return account
        except IntegrityError:
            db.rollback()  # the address was taken meanwhile: merge below
            other = get_by_email(db, email)
            if other is None:
                raise
    _set_token(other, token_response, scopes)
    merge_into(db, account_id, other.id)
    db.commit()
    db.expire_all()
    return other


def access_token(account: GmailAccount) -> str:
    """A fresh access token for the inbox."""
    return refresh_access_token(account.encrypted_refresh_token)


def label(account: GmailAccount) -> str:
    return account.email or UNKNOWN_INBOX


def summary_error(accounts: list[GmailAccount]) -> str | None:
    """The run's error for Settings: each failing inbox and its error
    ("you@school.edu: reconnect this inbox in Settings"), or None."""
    failing = [f"{label(a)}: {a.last_error}" for a in accounts if a.last_error]
    return "; ".join(failing)[:MAX_SUMMARY] if failing else None


def delete_account(db: Session, account_id: int) -> bool:
    """Remove the inbox and, by cascade, its suggestions. The run summary's
    error is recomputed from the inboxes left. False when there is none."""
    deleted = db.execute(delete(GmailAccount).where(GmailAccount.id == account_id)).rowcount
    if not deleted:
        db.rollback()
        return False
    db.flush()
    db.expire_all()  # suggestions of the inbox are gone from the database
    get_settings(db).gmail_last_error = summary_error(list_accounts(db))
    db.commit()
    return True
