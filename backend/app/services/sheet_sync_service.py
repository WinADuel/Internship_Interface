"""One-way backup of applications and contacts to a Google Sheet (spec §13.7).

Each sync rewrites whole tabs from the current DB state. At personal scale
that is simpler than row patching and self-healing, and it satisfies the
spec's "row re-synced". A sync failure is recorded, never raised."""

import enum
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.application import Application
from app.models.contact import Contact, ContactKind
from app.services.contact_service import last_status_changes
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import get_valid_access_token
from app.services.nudges import NudgeKind, compute_nudge
from app.services.settings_service import get_settings, nudge_settings
from app.services.sheets_client import GoogleSheetsClient, SheetsClient

logger = logging.getLogger(__name__)

SHEET_TITLE = "Internship Tracker Backup"
TAB_APPLICATIONS = "Applications"
TAB_PROFESSORS = "Professors"
TAB_COMPANY = "Company Contacts"
ALL_TABS = (TAB_APPLICATIONS, TAB_PROFESSORS, TAB_COMPANY)
CONTACT_TABS = (TAB_PROFESSORS, TAB_COMPANY)
HEADER_NOTE = "One-way backup mirror of Internship Tracker — edits made here are overwritten."
SHEET_URL = "https://docs.google.com/spreadsheets/d/{id}"
NOT_CONNECTED = "google not connected"
_ERROR_DETAIL_LIMIT = 300

APPLICATION_COLUMNS = (
    "id", "company", "role_title", "status", "priority", "date_applied", "follow_up_date",
    "interview_datetime", "job_link", "location", "source", "contact_person", "notes",
    "archived", "created_at", "updated_at",
)
CONTACT_COLUMNS = (
    "id", "name", "organization", "department", "title", "email", "email_confidence", "status",
    "closed_reason", "priority", "sent_at", "followed_up_at", "replied_at", "meeting_at",
    "application_id", "website_url", "profile_url", "draft_subject", "draft_body",
    "followup_subject", "followup_body", "notes", "origin", "archived", "updated_at",
)
NEEDS_ATTENTION_HEADER = "Needs Attention"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def application_rows(apps: Iterable[Application]) -> list[list[str]]:
    rows = [[HEADER_NOTE], list(APPLICATION_COLUMNS)]
    rows += [[_cell(getattr(a, col)) for col in APPLICATION_COLUMNS] for a in apps]
    return rows


def contact_rows(contacts_with_nudges: Iterable[tuple[Contact, NudgeKind | None]]) -> list[list[str]]:
    rows = [[HEADER_NOTE], [*CONTACT_COLUMNS, NEEDS_ATTENTION_HEADER]]
    rows += [
        [*(_cell(getattr(c, col)) for col in CONTACT_COLUMNS), _cell(nudge)]
        for c, nudge in contacts_with_nudges
    ]
    return rows


def _contacts_with_nudges(db: Session, kind: ContactKind) -> list[tuple[Contact, NudgeKind | None]]:
    settings = nudge_settings(get_settings(db))
    last_changes = last_status_changes(db)
    today = date.today()
    contacts = db.scalars(select(Contact).where(Contact.kind == kind).order_by(Contact.id))
    return [(c, compute_nudge(c, last_changes.get(c.id), settings, today)) for c in contacts]


def _tab_rows(db: Session, tab: str) -> list[list[str]]:
    if tab == TAB_APPLICATIONS:
        return application_rows(db.scalars(select(Application).order_by(Application.id)))
    if tab == TAB_PROFESSORS:
        return contact_rows(_contacts_with_nudges(db, ContactKind.PROFESSOR))
    if tab == TAB_COMPANY:
        return contact_rows(_contacts_with_nudges(db, ContactKind.COMPANY))
    raise ValueError(f"unknown tab {tab!r}")


def sync_tabs(db: Session, client: SheetsClient, tabs: Iterable[str], now: datetime | None = None) -> None:
    settings = get_settings(db)
    if settings.backup_sheet_id is None:
        settings.backup_sheet_id = client.create_spreadsheet(SHEET_TITLE, list(ALL_TABS))
        # Committed at once, so a later tab failure can't orphan a new sheet.
        db.commit()
    for tab in tabs:
        client.replace_tab(settings.backup_sheet_id, tab, _tab_rows(db, tab))


def safe_sync(
    db: Session,
    client_factory: Callable[[Session], SheetsClient],
    tabs: Iterable[str],
    now: datetime | None = None,
) -> bool:
    """Run a sync and record the outcome on the settings row. Never raises."""
    try:
        sync_tabs(db, client_factory(db), tabs, now=now)
        error = None
    except GoogleAuthError:
        error = NOT_CONNECTED
    except Exception as exc:  # noqa: BLE001 - a sync must never break the caller
        error = f"sheet sync failed: {str(exc)[:_ERROR_DETAIL_LIMIT]}"
    try:
        if error is not None:
            db.rollback()
        settings = get_settings(db)
        if error is None:
            settings.last_sheet_sync_at = now or datetime.now(timezone.utc)
        settings.last_sheet_sync_error = error
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record sheet sync outcome")
        db.rollback()
        return False
    if error is not None:
        logger.warning("sheet sync failed: %s", error)
    return error is None


def google_sheets_client(db: Session) -> SheetsClient:
    return GoogleSheetsClient(get_valid_access_token(db))


def sheet_url(sheet_id: str | None) -> str | None:
    return SHEET_URL.format(id=sheet_id) if sheet_id else None


class SheetSyncScheduler:
    """Queues a sync to run after the response, in its own DB session (the
    request session is closed by then)."""

    def schedule(self, background_tasks: BackgroundTasks, tabs: Iterable[str]) -> None:
        background_tasks.add_task(self.run, tuple(tabs))

    def run(self, tabs: tuple[str, ...]) -> None:
        db = SessionLocal()
        try:
            safe_sync(db, google_sheets_client, tabs)
        finally:
            db.close()
