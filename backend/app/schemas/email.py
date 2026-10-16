from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.application import ApplicationStatus
from app.models.contact import ContactStatus
from app.models.email_suggestion import EmailDirection, SuggestionKind, SuggestionState
from app.models.interview import InterviewKind
from app.schemas.interview import InterviewRoundCreate

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SuggestionRoundIn(InterviewRoundCreate):
    """The Phase 4 add-round form's fields for an interview suggestion. The
    round always goes to the suggestion's application, so `application_id`
    may be left out (a value sent here is ignored)."""

    application_id: int | None = None


class AcceptIn(BaseModel):
    """Optional details for Accept. `round`: an interview suggestion's round
    as edited in the add-round form (omitted: a round of the suggested kind
    with no date). `company`/`role_title`: a new-application suggestion's
    names as edited (omitted: the proposed ones). Fields that don't apply to
    the suggestion's kind are ignored."""

    round: SuggestionRoundIn | None = None
    company: Name | None = None
    role_title: Name | None = None


class SuggestionApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    role_title: str
    status: ApplicationStatus
    archived: bool


class SuggestionContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    organization: str
    status: ContactStatus


class EmailSuggestionOut(BaseModel):
    """Sender, subject and snippet are untrusted email text: show as text.
    `gmail_url` is the only link, built from the thread id and the inbox.
    `account_email` is the inbox the email came from (null when unknown)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_message_id: str
    gmail_thread_id: str
    gmail_url: str
    account_email: str | None
    received_at: datetime
    direction: EmailDirection
    from_name: str
    from_email: str
    subject: str
    snippet: str
    kind: SuggestionKind
    state: SuggestionState
    application_id: int | None
    contact_id: int | None
    proposed_company: str | None
    proposed_role: str | None
    # The round kind to prefill for an interview suggestion; null otherwise.
    round_kind: InterviewKind | None
    application: SuggestionApplicationOut | None
    contact: SuggestionContactOut | None
    created_at: datetime
    decided_at: datetime | None


class GmailAccountOut(BaseModel):
    """A connected inbox. `email` is null for an inbox carried over from
    Phase 6 until its first sync reads the address."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime


class EmailStatusOut(BaseModel):
    """`gmail_last_sync_at` and `gmail_last_error` summarise the last run;
    `accounts` holds each inbox's own, oldest first."""

    gmail_granted: bool
    gmail_sync_enabled: bool
    gmail_last_sync_at: datetime | None
    gmail_last_error: str | None
    pending_count: int
    accounts: list[GmailAccountOut]


class EmailSyncOut(EmailStatusOut):
    """Sync now's outcome: whether the run was clean (else see
    `gmail_last_error`), what it added, and whether mail was left for the
    next run."""

    ok: bool
    fetched: int
    suggested: int
    auto_applied: int
    more: bool

