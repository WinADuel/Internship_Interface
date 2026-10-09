"""One Gmail sync run (Phase 6 spec §6): list recent Inbox and Sent message
ids, fetch each new one's metadata (never a body), and store a suggestion
for each email the matcher proposes one for. Unmatched emails leave no
trace except the cursor.

The cursor (`app_settings.gmail_history_cursor`) is the newest Gmail
`internalDate` (ms) fully processed. A run asks for mail after the cursor
less an hour of overlap (late-arriving mail can carry an earlier date), and
ids already stored are skipped. New ids are processed oldest first, so the
cursor only ever advances past messages that were handled; Gmail lists
newest first, which this relies on. A run fetches at most MAX_FETCH
messages; the rest wait for the next run.

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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.contact import Contact
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.services.backup.lock import advisory_lock
from app.services.errors import GoogleAuthError
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
from app.services.google_docs_service import get_valid_access_token, is_gmail_granted
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
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_SPACES = re.compile(r"\s+")

GmailClientFactory = Callable[[Session], GmailClient]
SyncStatus = Literal["ok", "error", "disabled", "not_granted", "busy"]


@dataclass
class SyncReport:
    status: SyncStatus
    listed: int = 0  # ids Gmail returned that were not stored already
    fetched: int = 0  # messages fetched (metadata only)
    suggested: int = 0  # suggestions stored
    deleted: int = 0  # decided suggestions removed by retention
    error: str | None = None
    more: bool = False  # mail was left for the next run (MAX_FETCH reached)
    created: list[EmailSuggestion] = field(default_factory=list)


def google_gmail_client(db: Session) -> GmailClient:
    return GoogleGmailClient(get_valid_access_token(db))


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


def _known_ids(db: Session, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set(db.scalars(select(EmailSuggestion.gmail_message_id).where(EmailSuggestion.gmail_message_id.in_(ids))))


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
    db: Session, message: GmailMessage, headers: EmailHeaders, proposal: Proposal
) -> EmailSuggestion:
    """Add the suggestion row for a matched email (the caller commits)."""
    suggestion = EmailSuggestion(
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


def _process(db: Session, client: GmailClient, report: SyncReport, now: datetime) -> None:
    settings = get_settings(db)
    query = build_query(settings.gmail_history_cursor, settings.gmail_lookback_days, now)
    ids, more = client.list_message_ids(query, MAX_LIST)
    known = _known_ids(db, ids)
    new_ids = [i for i in dict.fromkeys(ids) if i not in known and is_gmail_id(i)]
    report.listed = len(new_ids)
    todo = list(reversed(new_ids))[:MAX_FETCH]  # oldest first
    report.more = more or len(new_ids) > MAX_FETCH
    snapshot = build_snapshot(db)
    for message_id in todo:
        message = client.get_metadata(message_id)
        if message is not None:
            report.fetched += 1
            headers = parse_message(message)
            proposal = propose(headers, snapshot)
            if proposal is not None and not _repeats_pending_new_application(db, proposal):
                report.created.append(store_suggestion(db, message, headers, proposal))
                report.suggested += 1
            cursor = int(settings.gmail_history_cursor or 0)
            if message.internal_date > cursor:
                settings.gmail_history_cursor = str(message.internal_date)
        # The suggestion and the cursor move together.
        db.commit()


def _record(db: Session, report: SyncReport, now: datetime) -> None:
    try:
        db.rollback()  # whatever failed mid-message is not kept
        settings = get_settings(db)
        if report.error is None:
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
    """One sync run. Skips quietly while sync is off or Gmail isn't granted,
    and returns `busy` while another run holds the lock. Never raises for a
    Gmail or Google failure: the error is recorded for Settings and the
    next run retries."""
    now = now or _now()
    deleted = delete_old_decided(db, now)
    settings = get_settings(db)
    if not settings.gmail_sync_enabled:
        return SyncReport("disabled", deleted=deleted)
    if not is_gmail_granted(db):
        return SyncReport("not_granted", deleted=deleted)

    with advisory_lock(db.get_bind().engine, GMAIL_LOCK_KEY) as locked:
        if not locked:
            return SyncReport("busy", deleted=deleted)
        report = SyncReport("ok", deleted=deleted)
        client = None
        try:
            client = client_factory(db)
            _process(db, client, report, now)
        except GoogleAuthError as exc:
            # Scrubbed by the service: status codes and exception types only.
            report.error = f"{exc}; {GMAIL_RECONNECT_HINT}"
        except GmailError as exc:
            report.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - a sync run must report, not crash
            logger.exception("gmail sync crashed")
            report.error = f"gmail sync failed unexpectedly ({type(exc).__name__})"
        finally:
            if client is not None:
                client.close()
        if report.error is not None:
            report.status = "error"
            report.error = report.error[:_ERROR_LIMIT]
            logger.warning("gmail sync: %s", report.error)
        _record(db, report, now)
        return report
