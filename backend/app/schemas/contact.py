from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.application import Priority
from app.models.contact import ContactKind, ContactOrigin, ContactStatus, EmailConfidence
from app.services.contact_transitions import ContactAction

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_NON_NULLABLE_FIELDS = ("kind", "name", "organization", "email_confidence", "priority")


class ContactCreate(BaseModel):
    kind: ContactKind
    name: RequiredText
    organization: RequiredText
    department: str | None = None
    title: str | None = None
    lab_name: str | None = None
    email: str | None = None
    email_confidence: EmailConfidence = EmailConfidence.NOT_FOUND
    website_url: str | None = None
    profile_url: str | None = None
    priority: Priority = Priority.MEDIUM
    notes: str | None = None
    application_id: int | None = None


class ContactUpdate(BaseModel):
    """Every user-editable field; omitted means unchanged. Status, dates and
    `archived` change only through their dedicated actions."""

    kind: ContactKind | None = None
    name: RequiredText | None = None
    organization: RequiredText | None = None
    department: str | None = None
    title: str | None = None
    lab_name: str | None = None
    email: str | None = None
    email_confidence: EmailConfidence | None = None
    website_url: str | None = None
    profile_url: str | None = None
    application_id: int | None = None
    draft_subject: str | None = None
    draft_body: str | None = None
    followup_subject: str | None = None
    followup_body: str | None = None
    priority: Priority | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "ContactUpdate":
        bad = [f for f in _NON_NULLABLE_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        return self


class SourceOut(BaseModel):
    label: str
    url: str


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ContactKind
    name: str
    organization: str
    department: str | None
    title: str | None
    lab_name: str | None
    email: str | None
    email_confidence: EmailConfidence
    website_url: str | None
    profile_url: str | None
    application_id: int | None
    relevance_note: str | None
    research_summary: str | None
    recent_work: str | None
    sources: list[SourceOut]
    draft_subject: str | None
    draft_body: str | None
    draft_edited: bool
    followup_subject: str | None
    followup_body: str | None
    followup_edited: bool
    draft_ready_at: datetime | None
    status: ContactStatus
    closed_reason: str | None
    priority: Priority
    sent_at: datetime | None
    followed_up_at: datetime | None
    replied_at: datetime | None
    meeting_at: datetime | None
    nudge_snoozed_until: date | None
    notes: str | None
    origin: ContactOrigin
    archived: bool
    created_at: datetime
    updated_at: datetime
    nudge: str | None = None


class ContactActionIn(BaseModel):
    action: ContactAction
    on: datetime | None = None
    meeting_at: datetime | None = None


class ContactStatusIn(BaseModel):
    new_status: ContactStatus


class SnoozeIn(BaseModel):
    days: int = Field(ge=1, le=30)


class ContactHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    old_status: ContactStatus | None
    new_status: ContactStatus
    changed_at: datetime


class ContactActivityOut(BaseModel):
    contact_id: int
    name: str
    organization: str
    kind: ContactKind
    old_status: ContactStatus | None
    new_status: ContactStatus
    changed_at: datetime
