"""Email suggestions (Phase 6 spec §4 "Suggested actions"): listing,
Accept, Dismiss, stale detection and auto-apply.

Accepting goes through the same services as clicking in the app
(`application_service.change_status` / `add_application`,
`contact_service.apply_action`, `interview_service.add_round`), so status
history, the contacts queue and the derived interview date behave the
same. Sheet sync needs FastAPI's BackgroundTasks, so callers schedule the
tabs an accept returns (the gmail-sync job syncs them itself).

A suggestion is valid only while its action still applies to the current
data; a pending one that no longer does is marked `stale` (and hidden)
when suggestions are listed or counted, when it is created, and when
someone tries to accept it."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.contact import Contact
from app.models.email_suggestion import EmailSuggestion, SuggestionKind, SuggestionState
from app.models.gmail_account import GmailAccount
from app.models.interview import InterviewKind
from app.schemas.application import ApplicationCreate
from app.schemas.email import AcceptIn
from app.schemas.interview import InterviewRoundCreate
from app.services import application_service, contact_service, interview_service
from app.services.contact_transitions import ACTIONS_BY_STATUS, ContactAction
from app.services.errors import (
    EmailSuggestionNotFoundError,
    SuggestionNotPendingError,
    SuggestionStaleError,
)
from app.services.gmail.classify import interview_round_kind
from app.services.gmail.matching import company_key
from app.services.sheet_sync_service import CONTACT_TABS, ROUND_SYNC_TABS, TAB_APPLICATIONS

K = SuggestionKind
APPLICATION_KINDS = frozenset({K.CONFIRMATION, K.REJECTION, K.INTERVIEW, K.ASSESSMENT, K.OFFER})
# Auto-apply covers only these (spec §3); the rest always wait for the owner.
AUTO_APPLY_KINDS = frozenset({K.CONFIRMATION, K.CONTACT_REPLY, K.CONTACT_SENT})
DECIDED_STATES = (SuggestionState.ACCEPTED, SuggestionState.DISMISSED, SuggestionState.AUTO_APPLIED)
# Statuses an interview email moves forward to `interview`.
_BEFORE_INTERVIEW = (ApplicationStatus.WISHLIST, ApplicationStatus.APPLIED, ApplicationStatus.PHONE_SCREEN)
# An application at one of these has its outcome; interview, assessment and
# rejection mail for it no longer applies.
_SETTLED = (ApplicationStatus.REJECTED, ApplicationStatus.OFFER)
ASSESSMENT_FOLLOW_UP = timedelta(days=7)
DEFAULT_ROLE = "Role not given"
GMAIL_THREAD_URL = "https://mail.google.com/mail/u/{inbox}/#all/{thread_id}"
StateFilter = Literal["pending", "decided", "all"]


@dataclass
class AcceptResult:
    suggestion: EmailSuggestion
    sheet_tabs: set[str] = field(default_factory=set)


def _now() -> datetime:
    return datetime.now(UTC)


def gmail_url(thread_id: str, account_email: str | None = None) -> str:
    """The thread in Gmail, in the inbox it came from (`/mail/u/<address>/`),
    or the browser's first signed-in account when the address isn't known.
    Thread ids are checked by the sync; the address is URL-encoded."""
    inbox = quote(account_email, safe="@") if account_email else "0"
    return GMAIL_THREAD_URL.format(inbox=inbox, thread_id=quote(thread_id, safe=""))


def round_kind(suggestion: EmailSuggestion) -> InterviewKind | None:
    if suggestion.kind != K.INTERVIEW:
        return None
    return interview_round_kind(suggestion.subject, suggestion.snippet)


def _application(db: Session, suggestion: EmailSuggestion) -> Application | None:
    if suggestion.application_id is None:
        return None
    application = db.get(Application, suggestion.application_id)
    return application if application is not None and not application.archived else None


def _contact(db: Session, contact_id: int | None) -> Contact | None:
    if contact_id is None:
        return None
    contact = db.get(Contact, contact_id)
    return contact if contact is not None and not contact.archived else None


def _contact_allows(contact: Contact | None, action: ContactAction) -> bool:
    return contact is not None and action in ACTIONS_BY_STATUS[contact.status]


def _tracked(db: Session, company: str | None) -> bool:
    key = company_key(company)
    companies = db.scalars(select(Application.company).where(Application.archived.is_(False)))
    return any(company_key(c) == key for c in companies)


def is_valid(db: Session, suggestion: EmailSuggestion) -> bool:
    """Whether the suggestion's action still applies to the current data."""
    kind = suggestion.kind
    if kind in APPLICATION_KINDS:
        application = _application(db, suggestion)
        if application is None:
            return False
        if kind == K.CONFIRMATION:
            return application.status == ApplicationStatus.WISHLIST or application.date_applied is None
        if kind == K.OFFER:
            return application.status != ApplicationStatus.OFFER
        return application.status not in _SETTLED
    if kind == K.CONTACT_REPLY:
        return _contact_allows(_contact(db, suggestion.contact_id), ContactAction.REPLIED)
    if kind == K.CONTACT_SENT:
        return _contact_allows(_contact(db, suggestion.contact_id), ContactAction.SENT)
    if kind == K.NEW_APPLICATION:
        return bool(company_key(suggestion.proposed_company)) and not _tracked(db, suggestion.proposed_company)
    return False


def _mark_stale(suggestion: EmailSuggestion, now: datetime) -> None:
    suggestion.state = SuggestionState.STALE
    suggestion.decided_at = now


def refresh_stale(db: Session, now: datetime | None = None) -> int:
    """Mark every pending suggestion that no longer applies as stale."""
    now = now or _now()
    stale = 0
    for suggestion in db.scalars(select(EmailSuggestion).where(EmailSuggestion.state == SuggestionState.PENDING)):
        if not is_valid(db, suggestion):
            _mark_stale(suggestion, now)
            stale += 1
    if stale:
        db.commit()
    return stale


def pending_count(db: Session, now: datetime | None = None) -> int:
    refresh_stale(db, now)
    return db.scalar(
        select(func.count()).select_from(EmailSuggestion).where(EmailSuggestion.state == SuggestionState.PENDING)
    )


def get_suggestion(db: Session, suggestion_id: int, *, lock: bool = False) -> EmailSuggestion:
    """`lock` takes the row lock (until the next commit) and re-reads the
    row, so two decisions on one suggestion run one after the other and the
    second sees the first's outcome."""
    if lock:
        suggestion = db.get(EmailSuggestion, suggestion_id, with_for_update=True, populate_existing=True)
    else:
        suggestion = db.get(EmailSuggestion, suggestion_id)
    if suggestion is None:
        raise EmailSuggestionNotFoundError(suggestion_id)
    return suggestion


def list_suggestions(
    db: Session,
    state: StateFilter = "pending",
    application_id: int | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> list[EmailSuggestion]:
    """`pending`: newest email first. `decided`: accepted, dismissed and
    auto-applied, most recently decided first. `all`: both, newest email
    first. Stale suggestions are never listed."""
    refresh_stale(db, now)
    query = select(EmailSuggestion)
    if state == "pending":
        query = query.where(EmailSuggestion.state == SuggestionState.PENDING)
    elif state == "decided":
        query = query.where(EmailSuggestion.state.in_(DECIDED_STATES))
    else:
        query = query.where(EmailSuggestion.state.in_((SuggestionState.PENDING, *DECIDED_STATES)))
    if application_id is not None:
        query = query.where(EmailSuggestion.application_id == application_id)
    if state == "decided":
        query = query.order_by(EmailSuggestion.decided_at.desc(), EmailSuggestion.id.desc())
    else:
        query = query.order_by(EmailSuggestion.received_at.desc(), EmailSuggestion.id.desc())
    return list(db.scalars(query.limit(limit)))


def related(db: Session, suggestions: list[EmailSuggestion]) -> tuple[dict[int, Application], dict[int, Contact]]:
    """The applications and contacts the suggestions point at, by id (two
    queries for the whole list)."""
    app_ids = {s.application_id for s in suggestions if s.application_id is not None}
    contact_ids = {s.contact_id for s in suggestions if s.contact_id is not None}
    applications = (
        {a.id: a for a in db.scalars(select(Application).where(Application.id.in_(app_ids)))} if app_ids else {}
    )
    contacts = (
        {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_(contact_ids)))} if contact_ids else {}
    )
    return applications, contacts


def account_emails(db: Session, suggestions: list[EmailSuggestion]) -> dict[int, str | None]:
    """The address of each inbox the suggestions came from, by inbox id."""
    ids = {s.gmail_account_id for s in suggestions if s.gmail_account_id is not None}
    if not ids:
        return {}
    return {row.id: row.email for row in db.execute(select(GmailAccount.id, GmailAccount.email).where(GmailAccount.id.in_(ids)))}


def dismiss(db: Session, suggestion_id: int, now: datetime | None = None) -> EmailSuggestion:
    suggestion = get_suggestion(db, suggestion_id, lock=True)
    if suggestion.state != SuggestionState.PENDING:
        raise SuggestionNotPendingError(suggestion_id)
    suggestion.state = SuggestionState.DISMISSED
    suggestion.decided_at = now or _now()
    db.commit()
    return suggestion


def _append_note(notes: str | None, line: str) -> str:
    return f"{notes.rstrip()}\n{line}" if notes and notes.strip() else line


def accept(
    db: Session,
    suggestion_id: int,
    data: AcceptIn | None = None,
    *,
    now: datetime | None = None,
    auto: bool = False,
) -> AcceptResult:
    """Carry out a pending suggestion's action (spec §4 table) and mark it
    accepted (`auto_applied` when the sync applies it). A suggestion that no
    longer applies is marked stale instead and SuggestionStaleError raised.
    Returns the sheet tabs the change touched."""
    now = now or _now()
    data = data or AcceptIn()
    suggestion = get_suggestion(db, suggestion_id, lock=True)
    if suggestion.state != SuggestionState.PENDING:
        raise SuggestionNotPendingError(suggestion_id)
    if not is_valid(db, suggestion):
        _mark_stale(suggestion, now)
        db.commit()
        raise SuggestionStaleError(suggestion_id)

    suggestion.state = SuggestionState.AUTO_APPLIED if auto else SuggestionState.ACCEPTED
    suggestion.decided_at = now
    received = suggestion.received_at.astimezone(UTC)
    tabs: set[str] = set()
    new_status: ApplicationStatus | None = None
    contact_action: ContactAction | None = None
    kind = suggestion.kind

    if kind in APPLICATION_KINDS:
        application = _application(db, suggestion)
        tabs.add(TAB_APPLICATIONS)
        if kind == K.CONFIRMATION:
            if application.date_applied is None:
                application.date_applied = received.date()
            if application.status == ApplicationStatus.WISHLIST:
                new_status = ApplicationStatus.APPLIED
        elif kind == K.REJECTION:
            new_status = ApplicationStatus.REJECTED
        elif kind == K.OFFER:
            new_status = ApplicationStatus.OFFER
        elif kind == K.ASSESSMENT:
            application.notes = _append_note(
                application.notes, f"Online assessment received {received.date().isoformat()}"
            )
            application.follow_up_date = received.date() + ASSESSMENT_FOLLOW_UP
        elif kind == K.INTERVIEW:
            if data.round is not None:
                fields = data.round.model_dump(exclude={"application_id"}, exclude_unset=True)
            else:
                fields = {"kind": round_kind(suggestion)}
            interview_service.add_round(db, InterviewRoundCreate(**fields, application_id=application.id))
            tabs.update(ROUND_SYNC_TABS)
            if application.status in _BEFORE_INTERVIEW:
                new_status = ApplicationStatus.INTERVIEW
        # Mail from a contact you emailed is also their reply (progress-log
        # ruling): mark them Replied when that is still a valid move.
        if _contact_allows(_contact(db, suggestion.contact_id), ContactAction.REPLIED):
            contact_action = ContactAction.REPLIED
    elif kind == K.CONTACT_REPLY:
        contact_action = ContactAction.REPLIED
    elif kind == K.CONTACT_SENT:
        contact_action = ContactAction.SENT
    elif kind == K.NEW_APPLICATION:
        application = application_service.add_application(
            db,
            ApplicationCreate(
                company=data.company or suggestion.proposed_company,
                role_title=data.role_title or suggestion.proposed_role or DEFAULT_ROLE,
                status=ApplicationStatus.APPLIED,
                date_applied=received.date(),
                source="Gmail",
            ),
        )
        suggestion.application_id = application.id
        tabs.add(TAB_APPLICATIONS)

    # Each of these services commits, saving everything above with it.
    if contact_action is not None:
        contact_service.apply_action(db, suggestion.contact_id, contact_action, on=received, now=now)
        tabs.update(CONTACT_TABS)
    if new_status is not None:
        application_service.change_status(db, suggestion.application_id, new_status)
    db.commit()
    return AcceptResult(suggestion, tabs)


def on_new_suggestion(
    db: Session, suggestion: EmailSuggestion, *, auto_apply: bool, now: datetime | None = None
) -> AcceptResult | None:
    """The sync's step for a suggestion it just stored: one that already
    doesn't apply is stale from the start; with auto-apply on, the safe
    kinds are applied at once. Returns the accept result when applied.

    A contact's mail stored as an application update that no longer applies
    (a rejection for an application already rejected) is still their reply:
    it becomes a contact reply while the contact can be marked Replied."""
    now = now or _now()
    if (
        suggestion.kind in APPLICATION_KINDS
        and not is_valid(db, suggestion)
        and _contact_allows(contact := _contact(db, suggestion.contact_id), ContactAction.REPLIED)
    ):
        suggestion.kind = K.CONTACT_REPLY
        suggestion.application_id = contact.application_id
        db.flush()
    if not is_valid(db, suggestion):
        _mark_stale(suggestion, now)
        db.commit()
        return None
    if auto_apply and suggestion.kind in AUTO_APPLY_KINDS:
        return accept(db, suggestion.id, now=now, auto=True)
    return None
