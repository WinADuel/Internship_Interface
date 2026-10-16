"""One Gmail sync run (Phase 6 spec §6; Phase 7 spec §4 for more than one
inbox): for each connected inbox, oldest first, list recent Inbox and Sent
message ids, fetch each new one's metadata (never a body), and store a
suggestion for each email the matcher proposes one for. Unmatched emails
leave no trace except the inbox's cursor.

Each inbox has its own client, cursor (`gmail_accounts.history_cursor`) and
outcome (`last_sync_at`, `last_error`); one failing is recorded on that
inbox and the run goes on to the next. `app_settings.gmail_last_sync_at` and
`gmail_last_error` summarise the run. An inbox carried over from Phase 6
without an address reads it from Gmail's profile first; if another inbox
already has that address, its suggestions move there and the row goes.

The cursor is a Gmail `internalDate` (ms) up to which the inbox's mail was
handled, never later than the run's start time. A run asks for mail after
the cursor less an hour of overlap (late-arriving mail can carry an earlier
date), and ids the inbox already stored are skipped. New ids are handled
oldest first in Gmail's list order (newest first); after each one the
cursor moves to that message's date, and only a run that handled everything
it listed moves it to the newest date it saw. So a run that stops early (an
error, MAX_FETCH, sync turned off) leaves the cursor at the last message it
handled. A run fetches at most MAX_FETCH messages per inbox; the rest wait
for the next run. Listing stops at MAX_LIST ids, newest first: older mail
beyond that in one window is never looked at.

A message that fails to process (anything but a Gmail or Google error) is
rolled back, logged by type and Gmail id only, counted as skipped, and
passed over so it can't block later mail.

The gmail-sync job and Sync now share a Postgres advisory lock, so two runs
never overlap. Every run also deletes decided suggestions older than
RETENTION, even while sync is off."""

import html
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.contact import Contact
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.models.gmail_account import GmailAccount
from app.services import email_suggestion_service
from app.services.backup.lock import advisory_lock
from app.services.errors import GoogleAuthError
from app.services.gmail import accounts
from app.services.gmail.client import (
    GMAIL_RECONNECT_HINT,
    GmailClient,
    GmailError,
    GmailMessage,
    GoogleGmailClient,
    is_gmail_id,
)
from app.services.gmail.matching import (
    ApplicationRef,
    ContactRef,
    EmailHeaders,
    Proposal,
    Snapshot,
    company_key,
    propose,
)
from app.services.google_docs_service import is_gmail_granted
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

# Fixed key for pg_(try_)advisory_lock: "GMAILSYN" in ASCII, distinct from
# the scan ("JOBSCAN") and backup ("DBBACKUP") locks.
GMAIL_LOCK_KEY = int.from_bytes(b"GMAILSYN", "big")
# Inbox and Sent, without Promotions, Social and chats (spec §3).
BASE_QUERY = "{in:inbox in:sent} -category:promotions -category:social -in:chats"
OVERLAP = timedelta(hours=1)
MAX_FETCH = 500  # message fetches per run (spec §6)
MAX_LIST = 5000  # ids listed per run; far more than a lookback ever holds
RETENTION = timedelta(days=90)
MAX_SUBJECT = 300
MAX_SNIPPET = 300
MAX_NAME = 200
MAX_EMAIL = 320
_ERROR_LIMIT = 300
GMAIL_PERMISSION_MISSING = "No Gmail inbox connected: use Connect Gmail in Settings"
RETRY_HINT = "it will retry next run"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_SPACES = re.compile(r"\s+")

GmailClientFactory = Callable[[Session, GmailAccount], GmailClient]
SyncStatus = Literal["ok", "error", "disabled", "not_granted", "busy"]
# How one inbox's turn in a run ended.
InboxStatus = Literal["ok", "error", "disabled", "removed", "merged"]


@dataclass
class InboxReport:
    account_id: int
    status: InboxStatus = "ok"
    error: str | None = None


@dataclass
class SyncReport:
    """A run's outcome, its counts summed over inboxes. `error` is the
    run's summary (each failing inbox and its error); `status` is "error"
    when any inbox failed."""

    status: SyncStatus
    listed: int = 0  # ids Gmail returned that were not stored already
    fetched: int = 0  # messages fetched (metadata only)
    suggested: int = 0  # suggestions stored
    auto_applied: int = 0  # of those, applied at once (auto-apply)
    deleted: int = 0  # decided suggestions removed by retention
    skipped: int = 0  # messages that failed to process and were passed over
    error: str | None = None
    more: bool = False  # mail was left for the next run (MAX_FETCH reached)
    created: list[EmailSuggestion] = field(default_factory=list)
    sheet_tabs: set[str] = field(default_factory=set)  # touched by auto-apply
    inboxes: list[InboxReport] = field(default_factory=list)


def google_gmail_client(db: Session, account: GmailAccount) -> GmailClient:
    return GoogleGmailClient(accounts.access_token(account))


def _now() -> datetime:
    return datetime.now(UTC)


def clean_text(value: str | None, limit: int) -> str:
    """Untrusted header or snippet text as stored: control characters and
    runs of whitespace become one space, then capped."""
    value = _CONTROL.sub(" ", value or "")
    return _SPACES.sub(" ", value).strip()[:limit]


def _decode(value: str) -> str:
    """Decode RFC 2047 encoded words (`=?UTF-8?B?...?=`); undecodable input
    is kept as it came."""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - bad charsets and malformed words come in many forms
        return value


def _addresses(value: str | None) -> tuple[str, ...]:
    return tuple(
        clean_text(address, MAX_EMAIL).casefold()
        for _, address in getaddresses([value or ""])
        if "@" in address
    )


def parse_message(message: GmailMessage) -> EmailHeaders:
    """The headers the matcher reads, decoded, cleaned and capped. Mail with
    the SENT label is outbound; everything else is inbound."""
    headers = message.headers
    name, address = parseaddr(headers.get("from", ""))
    direction = EmailDirection.SENT if "SENT" in message.label_ids else EmailDirection.INBOUND
    return EmailHeaders(
        direction=direction,
        from_name=clean_text(_decode(name), MAX_NAME),
        from_email=clean_text(address, MAX_EMAIL).casefold(),
        subject=clean_text(_decode(headers.get("subject", "")), MAX_SUBJECT),
        # Gmail's snippet is HTML-escaped ("we&#39;d"); it is stored as text.
        snippet=clean_text(html.unescape(message.snippet), MAX_SNIPPET),
        received_at=datetime.fromtimestamp(message.internal_date / 1000, tz=UTC),
        to_emails=_addresses(headers.get("to")),
        cc_emails=_addresses(headers.get("cc")),
    )


def build_snapshot(db: Session) -> Snapshot:
    """Every application (the matcher skips archived ones itself) and every
    non-archived contact with an email address."""
    applications = [
        ApplicationRef(a.id, a.company, a.role_title, a.status, a.archived, a.updated_at)
        for a in db.scalars(select(Application).order_by(Application.id))
    ]
    contacts = [
        ContactRef(c.id, c.email, c.status, c.application_id)
        for c in db.scalars(
            select(Contact)
            .where(Contact.archived.is_(False), Contact.email.is_not(None))
            .order_by(Contact.id)
        )
    ]
    return Snapshot(applications=applications, contacts=contacts)


def build_query(cursor: str | None, lookback_days: int, now: datetime) -> str:
    """The messages.list query: the first run looks back `lookback_days`;
    later runs start an hour before the cursor, but never further back than
    the lookback (sync turned back on after a long pause)."""
    try:
        cursor_ms = int(cursor) if cursor else None
    except ValueError:
        cursor_ms = None
    if cursor_ms is None:
        return f"{BASE_QUERY} newer_than:{lookback_days}d"
    after = datetime.fromtimestamp(cursor_ms / 1000, tz=UTC) - OVERLAP
    after = max(after, now - timedelta(days=lookback_days))
    return f"{BASE_QUERY} after:{int(after.timestamp())}"


def delete_old_decided(db: Session, now: datetime) -> int:
    """Retention (spec §3): decided suggestions go 90 days after the
    decision; pending ones stay until decided."""
    result = db.execute(
        delete(EmailSuggestion).where(
            EmailSuggestion.state != SuggestionState.PENDING,
            EmailSuggestion.decided_at < now - RETENTION,
        )
    )
    db.commit()
    return result.rowcount or 0


def _known_ids(db: Session, account_id: int, ids: list[str]) -> set[str]:
    """The ids the inbox already stored (message ids are per mailbox)."""
    if not ids:
        return set()
    return set(
        db.scalars(
            select(EmailSuggestion.gmail_message_id).where(
                EmailSuggestion.gmail_account_id == account_id, EmailSuggestion.gmail_message_id.in_(ids)
            )
        )
    )


def _repeats_pending_new_application(db: Session, proposal: Proposal) -> bool:
    """Whether a pending "add <company>" suggestion already exists for the
    proposal's company (a confirmation and then an interview invitation from
    the same untracked company make one suggestion, not two)."""
    if proposal.kind != SuggestionKind.NEW_APPLICATION:
        return False
    key = company_key(proposal.proposed_company)
    pending = db.scalars(
        select(EmailSuggestion.proposed_company).where(
            EmailSuggestion.kind == SuggestionKind.NEW_APPLICATION,
            EmailSuggestion.state == SuggestionState.PENDING,
        )
    )
    return any(company_key(company) == key for company in pending)


def store_suggestion(
    db: Session, message: GmailMessage, headers: EmailHeaders, proposal: Proposal, account_id: int
) -> EmailSuggestion:
    """Add the suggestion row for a matched email of the inbox `account_id`
    (the caller commits)."""
    suggestion = EmailSuggestion(
        gmail_account_id=account_id,
        gmail_message_id=message.id,
        gmail_thread_id=message.thread_id,
        received_at=headers.received_at,
        direction=headers.direction,
        from_name=headers.from_name,
        from_email=headers.from_email,
        subject=headers.subject,
        snippet=headers.snippet,
        kind=proposal.kind,
        application_id=proposal.application_id,
        contact_id=proposal.contact_id,
        proposed_company=proposal.proposed_company,
        proposed_role=proposal.proposed_role,
        state=SuggestionState.PENDING,
    )
    db.add(suggestion)
    db.flush()
    return suggestion


def _cursor_ms(cursor: str | None) -> int:
    try:
        return int(cursor) if cursor else 0
    except ValueError:
        return 0


def _handle(
    db: Session, account_id: int, message: GmailMessage, snapshot: Snapshot, report: SyncReport, now: datetime
) -> Snapshot:
    """Store the suggestion (if any) for one fetched message; the caller
    commits. Returns the snapshot to match the next message against."""
    headers = parse_message(message)
    proposal = propose(headers, snapshot)
    if proposal is None or _repeats_pending_new_application(db, proposal):
        return snapshot
    suggestion = store_suggestion(db, message, headers, proposal, account_id)
    report.suggested += 1
    # May commit (stale or auto-applied); the caller then moves the cursor.
    applied = email_suggestion_service.on_new_suggestion(
        db, suggestion, auto_apply=get_settings(db).gmail_auto_apply, now=now
    )
    report.created.append(suggestion)
    if applied is None:
        return snapshot
    report.auto_applied += 1
    report.sheet_tabs |= applied.sheet_tabs
    # A contact marked Sent can now be matched as replying.
    return build_snapshot(db)


def _account_exists(db: Session, account_id: int) -> bool:
    return db.scalar(select(GmailAccount.id).where(GmailAccount.id == account_id)) is not None


def _stop_reason(db: Session, account_id: int) -> InboxStatus | None:
    """Why the inbox's turn must stop now: sync was turned off (which ends
    the whole run) or the inbox was removed while it ran (checked after
    each message)."""
    if not get_settings(db).gmail_sync_enabled:
        return "disabled"
    if not _account_exists(db, account_id):
        return "removed"
    return None


def _cursor(db: Session, account_id: int) -> str | None:
    return db.scalar(select(GmailAccount.history_cursor).where(GmailAccount.id == account_id))


def _set_cursor(db: Session, account_id: int, value: int) -> None:
    # A plain UPDATE: an inbox removed meanwhile matches no row, no error.
    db.execute(update(GmailAccount).where(GmailAccount.id == account_id).values(history_cursor=str(value)))


def _advance_cursor(db: Session, account_id: int, start: int, date: int) -> None:
    """Move the cursor to the message just handled. The run may stop after
    it, so the cursor goes only as far as this one, the last handled in list
    order: one handled earlier may carry a later date than mail not yet
    handled. It never moves back past where the run started."""
    _set_cursor(db, account_id, max(start, date))


def _process(
    db: Session, client: GmailClient, account_id: int, report: SyncReport, now: datetime
) -> InboxStatus:
    """One inbox's mail. Returns "disabled" or "removed" when it stopped
    early for that reason, else "ok"."""
    settings = get_settings(db)
    cursor = _cursor(db, account_id)
    start = _cursor_ms(cursor)
    query = build_query(cursor, settings.gmail_lookback_days, now)
    ids, more = client.list_message_ids(query, MAX_LIST)
    known = _known_ids(db, account_id, ids)
    new_ids = [i for i in dict.fromkeys(ids) if i not in known and is_gmail_id(i)]
    report.listed += len(new_ids)
    todo = list(reversed(new_ids))[:MAX_FETCH]  # oldest first
    capped = more or len(new_ids) > MAX_FETCH
    report.more = report.more or capped
    snapshot = build_snapshot(db)
    # A message dated in the future must not move the cursor past mail that
    # hasn't arrived yet.
    now_ms = int(now.timestamp() * 1000)
    newest = start
    for message_id in todo:
        date: int | None = None
        try:
            message = client.get_metadata(message_id)
            if message is not None:
                report.fetched += 1
                date = min(message.internal_date, now_ms)
                snapshot = _handle(db, account_id, message, snapshot, report, now)
                _advance_cursor(db, account_id, start, date)
            # The suggestion and the cursor move together.
            db.commit()
        except (GmailError, GoogleAuthError):
            raise  # Gmail itself failed: stop, and the next run retries this message
        except Exception as exc:  # noqa: BLE001 - one bad message must not block later mail
            # Type and id only: the exception's text can quote the email.
            db.rollback()
            report.skipped += 1
            logger.warning("gmail sync skipped message %s (%s)", message_id, type(exc).__name__)
            if date is not None:
                _advance_cursor(db, account_id, start, date)
                db.commit()
        if date is not None:
            newest = max(newest, date)
        stop = _stop_reason(db, account_id)
        if stop is not None:
            return stop
    # A run that handled everything it listed moves the cursor to the newest
    # date it saw. So does a capped run that would otherwise not move it at
    # all (out-of-order dates at the oldest end of the list): the next run
    # would list and handle the same messages again, forever.
    if newest > start and (not capped or _cursor_ms(_cursor(db, account_id)) <= start):
        _set_cursor(db, account_id, newest)
        db.commit()
    return "ok"


def _learn_address(db: Session, client: GmailClient, account: GmailAccount) -> GmailAccount | None:
    """For an inbox without an address (carried over from Phase 6): read it
    from Gmail's profile. If another inbox already has it, this row's
    suggestions move there (those it already holds are dropped) and the row
    is removed: returns None, as that inbox gets its own turn."""
    address = client.get_profile()
    other = accounts.get_by_email(db, address)
    if other is None:
        account.email = address
        db.commit()
        return account
    held = select(EmailSuggestion.gmail_message_id).where(EmailSuggestion.gmail_account_id == other.id)
    db.execute(
        delete(EmailSuggestion).where(
            EmailSuggestion.gmail_account_id == account.id, EmailSuggestion.gmail_message_id.in_(held)
        )
    )
    db.execute(
        update(EmailSuggestion).where(EmailSuggestion.gmail_account_id == account.id).values(gmail_account_id=other.id)
    )
    db.execute(delete(GmailAccount).where(GmailAccount.id == account.id))
    db.commit()
    db.expire_all()
    logger.info("gmail sync: inbox %d is %d's address; merged into it", account.id, other.id)
    return None


def _sync_inbox(
    db: Session, client_factory: GmailClientFactory, account: GmailAccount, report: SyncReport, now: datetime
) -> InboxReport:
    inbox = InboxReport(account.id)
    client = None
    try:
        client = client_factory(db, account)
        if account.email is None and _learn_address(db, client, account) is None:
            inbox.status = "merged"
            return inbox
        inbox.status = _process(db, client, account.id, report, now)
    except GoogleAuthError as exc:
        # Scrubbed by the service: status codes and exception types only.
        inbox.error = f"{exc}; {GMAIL_RECONNECT_HINT if exc.reconnect else RETRY_HINT}"
    except GmailError as exc:
        inbox.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - one inbox must not stop the others
        logger.exception("gmail sync crashed on inbox %d", account.id)
        inbox.error = f"gmail sync failed unexpectedly ({type(exc).__name__})"
    finally:
        if client is not None:
            client.close()
    if inbox.error is not None:
        inbox.status = "error"
        inbox.error = inbox.error[:_ERROR_LIMIT]
        logger.warning("gmail sync of inbox %d: %s", account.id, inbox.error)
    return inbox


def _record_inbox(db: Session, inbox: InboxReport, now: datetime) -> None:
    """The inbox's own outcome: a clean turn sets its last-sync time and
    clears its error; a failed one records the error. A turn stopped by
    sync being turned off changes neither."""
    if inbox.status not in ("ok", "error"):
        return
    try:
        db.rollback()  # whatever failed mid-message is not kept
        values = {"last_error": inbox.error}
        if inbox.status == "ok":
            values["last_sync_at"] = now
        db.execute(update(GmailAccount).where(GmailAccount.id == inbox.account_id).values(**values))
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the gmail sync outcome of inbox %d", inbox.account_id)
        db.rollback()


def _record(db: Session, report: SyncReport, now: datetime) -> None:
    """The run's summary on app_settings: the last-sync time moves when at
    least one inbox synced; the error lists the failing inboxes, or is
    cleared. A run stopped by sync being turned off changes neither."""
    try:
        db.rollback()
        settings = get_settings(db)
        if report.status == "not_granted":
            settings.gmail_last_error = GMAIL_PERMISSION_MISSING
        elif report.status != "disabled":
            if any(i.status == "ok" for i in report.inboxes):
                settings.gmail_last_sync_at = now
            settings.gmail_last_error = report.error
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the gmail sync outcome")
        db.rollback()


def run_sync(
    db: Session,
    client_factory: GmailClientFactory = google_gmail_client,
    *,
    now: datetime | None = None,
) -> SyncReport:
    """One sync run over every connected inbox. Skips quietly while sync is
    off; while no inbox is connected it records that for Settings. Returns
    `busy` while another run holds the lock. A run stops after the message
    in hand when sync is turned off; an inbox removed meanwhile stops only
    its own turn. Never raises for a Gmail or Google failure: the error is
    recorded on the inbox and in the summary, and the next run retries."""
    now = now or _now()
    deleted = delete_old_decided(db, now)
    settings = get_settings(db)
    if not settings.gmail_sync_enabled:
        return SyncReport("disabled", deleted=deleted)
    if not is_gmail_granted(db):
        # Sync is on but no inbox is connected (every one was removed).
        report = SyncReport("not_granted", deleted=deleted)
        _record(db, report, now)
        return report

    with advisory_lock(db.get_bind().engine, GMAIL_LOCK_KEY) as locked:
        if not locked:
            return SyncReport("busy", deleted=deleted)
        report = SyncReport("ok", deleted=deleted)
        for account_id in [a.id for a in accounts.list_accounts(db)]:
            account = db.get(GmailAccount, account_id)
            if account is None:
                continue  # merged into another inbox, or removed, meanwhile
            inbox = _sync_inbox(db, client_factory, account, report, now)
            _record_inbox(db, inbox, now)
            report.inboxes.append(inbox)
            if inbox.status == "disabled":
                report.status = "disabled"
                break
        db.rollback()
        if report.status != "disabled":
            remaining = accounts.list_accounts(db)
            if not remaining:
                report.status = "not_granted"  # every inbox was removed while it ran
            elif any(i.status == "error" for i in report.inboxes):
                report.status = "error"
                report.error = accounts.summary_error(remaining)
        _record(db, report, now)
        return report
