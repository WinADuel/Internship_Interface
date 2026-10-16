"""Connected Gmail inboxes (Phase 7 spec §4): add or reconnect one from a
Connect Gmail consent, list and remove them, and the access token for one.

Each inbox has its own refresh token, from a consent that asked for
gmail.readonly only, so adding or removing an inbox never touches the
Drive/Docs connection (`oauth_tokens`). Removing an inbox deletes its
email suggestions (ON DELETE CASCADE); nothing is revoked at Google."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import encrypt_value
from app.models.gmail_account import GmailAccount
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import refresh_access_token
from app.services.settings_service import get_settings

UNKNOWN_INBOX = "Gmail inbox"  # an inbox's label while its address is unknown
MAX_SUMMARY = 1000


def list_accounts(db: Session) -> list[GmailAccount]:
    """Every inbox, oldest first."""
    return list(db.scalars(select(GmailAccount).order_by(GmailAccount.created_at, GmailAccount.id)))


def get_by_email(db: Session, email: str) -> GmailAccount | None:
    return db.scalars(select(GmailAccount).where(GmailAccount.email == email)).first()


def upsert_account(db: Session, email: str, token_response: dict, scopes: str) -> GmailAccount:
    """Store a consent's token for the inbox `email` (already lower-cased):
    a new inbox is added; an existing one gets the new token and its error
    cleared (Reconnect). An existing inbox keeps its refresh token when the
    response has none."""
    refresh_token = token_response.get("refresh_token")
    account = get_by_email(db, email)
    if account is None:
        if not refresh_token:
            raise GoogleAuthError("google did not return a refresh token")
        account = GmailAccount(email=email)
        db.add(account)
    if refresh_token:
        account.encrypted_refresh_token = encrypt_value(refresh_token)
    account.scopes = scopes
    account.last_error = None
    db.commit()
    return account


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
