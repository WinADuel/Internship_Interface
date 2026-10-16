"""Email updates (Phase 6 spec §4, §7): the suggestions Gmail sync found,
Accept and Dismiss, the status for Settings and the nav badge, and Sync
now; the connected inboxes (Phase 7 spec §4). Cookie auth only; the Claude token is refused like on every other
cookie route, and no email data is reachable from /api/claude."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_gmail_client_factory, get_sheet_sync_scheduler
from app.db.session import get_db
from app.models.application import Application
from app.models.contact import Contact
from app.models.email_suggestion import EmailSuggestion
from app.schemas.email import (
    AcceptIn,
    EmailStatusOut,
    EmailSuggestionOut,
    EmailSyncOut,
    GmailAccountOut,
    SuggestionApplicationOut,
    SuggestionContactOut,
)
from app.services import email_suggestion_service as suggestions
from app.services.email_suggestion_service import StateFilter
from app.services.errors import (
    EmailSuggestionNotFoundError,
    SuggestionNotPendingError,
    SuggestionStaleError,
)
from app.services.gmail import accounts as gmail_accounts
from app.services.gmail.sync import GmailClientFactory, run_sync
from app.services.google_docs_service import is_gmail_granted
from app.services.settings_service import get_settings
from app.services.sheet_sync_service import ALL_TABS, SheetSyncScheduler

router = APIRouter(
    prefix="/api/email",
    tags=["email"],
    dependencies=[Depends(get_current_user)],
)

MAX_LIMIT = 200
NOT_GRANTED = "connect Gmail in Settings first"
NOT_ENABLED = "turn on Gmail sync in Settings first"
# EmailSuggestionOut fields read straight off the row; the rest are built.
_COLUMNS = tuple(
    name
    for name in EmailSuggestionOut.model_fields
    if name not in {"gmail_url", "account_email", "round_kind", "application", "contact"}
)


def _out(
    suggestion: EmailSuggestion,
    applications: dict[int, Application],
    contacts: dict[int, Contact],
    inboxes: dict[int, str | None],
) -> EmailSuggestionOut:
    application = applications.get(suggestion.application_id)
    contact = contacts.get(suggestion.contact_id)
    account_email = inboxes.get(suggestion.gmail_account_id)
    return EmailSuggestionOut(
        **{name: getattr(suggestion, name) for name in _COLUMNS},
        gmail_url=suggestions.gmail_url(suggestion.gmail_thread_id, account_email),
        account_email=account_email,
        round_kind=suggestions.round_kind(suggestion),
        application=SuggestionApplicationOut.model_validate(application) if application else None,
        contact=SuggestionContactOut.model_validate(contact) if contact else None,
    )


def _many(db: Session, rows: list[EmailSuggestion]) -> list[EmailSuggestionOut]:
    applications, contacts = suggestions.related(db, rows)
    inboxes = suggestions.account_emails(db, rows)
    return [_out(s, applications, contacts, inboxes) for s in rows]


def _one(db: Session, suggestion: EmailSuggestion) -> EmailSuggestionOut:
    return _many(db, [suggestion])[0]


def _accounts(db: Session) -> list[GmailAccountOut]:
    return [GmailAccountOut.model_validate(a) for a in gmail_accounts.list_accounts(db)]


def _status(db: Session) -> dict:
    settings = get_settings(db)
    return {
        "gmail_granted": is_gmail_granted(db),
        "gmail_sync_enabled": settings.gmail_sync_enabled,
        "gmail_last_sync_at": settings.gmail_last_sync_at,
        "gmail_last_error": settings.gmail_last_error,
        "pending_count": suggestions.pending_count(db),
        "accounts": _accounts(db),
    }


def _schedule(background_tasks: BackgroundTasks, sync: SheetSyncScheduler, tabs: set[str]) -> None:
    if tabs:
        sync.schedule(background_tasks, [t for t in ALL_TABS if t in tabs])


@router.get("/suggestions", response_model=list[EmailSuggestionOut])
def list_suggestions(
    state: StateFilter = "pending",
    application_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
    db: Session = Depends(get_db),
):
    rows = suggestions.list_suggestions(db, state, application_id=application_id, limit=limit)
    return _many(db, rows)


@router.get("/accounts", response_model=list[GmailAccountOut])
def list_accounts(db: Session = Depends(get_db)):
    """The connected Gmail inboxes, oldest first."""
    return _accounts(db)


@router.delete("/accounts/{account_id}", status_code=204)
def remove_account(account_id: int, db: Session = Depends(get_db)):
    """Remove an inbox and its stored email updates. Changes already applied
    to applications and contacts stay; nothing is revoked at Google."""
    if not gmail_accounts.delete_account(db, account_id):
        raise HTTPException(status_code=404, detail="gmail inbox not found")
    return Response(status_code=204)


@router.post("/suggestions/{suggestion_id}/accept", response_model=EmailSuggestionOut)
def accept_suggestion(
    suggestion_id: int,
    background_tasks: BackgroundTasks,
    data: Annotated[AcceptIn | None, Body()] = None,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        result = suggestions.accept(db, suggestion_id, data)
    except EmailSuggestionNotFoundError:
        raise HTTPException(status_code=404, detail="email suggestion not found")
    except SuggestionNotPendingError:
        raise HTTPException(status_code=409, detail="this suggestion was already decided")
    except SuggestionStaleError:
        raise HTTPException(status_code=409, detail="this suggestion no longer applies")
    _schedule(background_tasks, sync, result.sheet_tabs)
    return _one(db, result.suggestion)


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=EmailSuggestionOut)
def dismiss_suggestion(suggestion_id: int, db: Session = Depends(get_db)):
    try:
        suggestion = suggestions.dismiss(db, suggestion_id)
    except EmailSuggestionNotFoundError:
        raise HTTPException(status_code=404, detail="email suggestion not found")
    except SuggestionNotPendingError:
        raise HTTPException(status_code=409, detail="this suggestion was already decided")
    return _one(db, suggestion)


@router.get("/status", response_model=EmailStatusOut)
def email_status(db: Session = Depends(get_db)):
    return EmailStatusOut(**_status(db))


@router.post("/sync", response_model=EmailSyncOut)
def sync_now(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    client_factory: GmailClientFactory = Depends(get_gmail_client_factory),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    """Run a Gmail sync now and return the new status (a failure shows as
    `ok: false` and `gmail_last_error`). 409 while the gmail-sync job is
    running one; 400 while Gmail isn't connected or sync is off."""
    if not is_gmail_granted(db):
        raise HTTPException(status_code=400, detail=NOT_GRANTED)
    report = run_sync(db, client_factory)
    if report.status == "not_granted":
        raise HTTPException(status_code=400, detail=NOT_GRANTED)
    if report.status == "disabled":
        raise HTTPException(status_code=400, detail=NOT_ENABLED)
    if report.status == "busy":
        raise HTTPException(status_code=409, detail="a Gmail sync is already running")
    _schedule(background_tasks, sync, report.sheet_tabs)
    return EmailSyncOut(
        **_status(db),
        ok=report.status == "ok",
        fetched=report.fetched,
        suggested=report.suggested,
        auto_applied=report.auto_applied,
        more=report.more,
    )
