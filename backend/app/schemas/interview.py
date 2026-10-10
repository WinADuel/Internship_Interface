from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.interview import InterviewFormat, InterviewKind, InterviewOutcome, InterviewState

# Caps from the Phase 4 spec §3.
MAX_CHECKLIST_ITEMS = 30

ChecklistLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ChecklistId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Title = Annotated[str, StringConstraints(max_length=200)]
ShortText = Annotated[str, StringConstraints(max_length=500)]
LongNotes = Annotated[str, StringConstraints(max_length=20_000)]
Questions = Annotated[str, StringConstraints(max_length=5_000)]
Duration = Annotated[int, Field(ge=5, le=600)]

_NON_NULLABLE_FIELDS = ("kind", "state", "checklist")


class ChecklistItem(BaseModel):
    """`id` may be omitted for a new item; the service assigns one."""

    id: ChecklistId | None = None
    label: ChecklistLabel
    done: bool = False


Checklist = Annotated[list[ChecklistItem], Field(max_length=MAX_CHECKLIST_ITEMS)]


def _unique_ids(checklist: list[ChecklistItem] | None) -> None:
    ids = [item.id for item in checklist or [] if item.id is not None]
    if len(ids) != len(set(ids)):
        raise ValueError("checklist item ids must be unique")


class InterviewRoundCreate(BaseModel):
    """A new round. An omitted `checklist` gets the default one."""

    application_id: int
    kind: InterviewKind = InterviewKind.OTHER
    title: Title | None = None
    scheduled_at: AwareDatetime | None = None
    duration_minutes: Duration | None = None
    format: InterviewFormat | None = None
    location: ShortText | None = None
    interviewers: ShortText | None = None
    state: InterviewState = InterviewState.SCHEDULED
    outcome: InterviewOutcome | None = None
    prep_notes: LongNotes | None = None
    questions_to_ask: Questions | None = None
    reflection: LongNotes | None = None
    checklist: Checklist | None = None
    thank_you_sent_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _checklist_ids_unique(self) -> "InterviewRoundCreate":
        _unique_ids(self.checklist)
        return self


class InterviewRoundUpdate(BaseModel):
    """Omitted means unchanged. A round never moves to another application."""

    kind: InterviewKind | None = None
    title: Title | None = None
    scheduled_at: AwareDatetime | None = None
    duration_minutes: Duration | None = None
    format: InterviewFormat | None = None
    location: ShortText | None = None
    interviewers: ShortText | None = None
    state: InterviewState | None = None
    outcome: InterviewOutcome | None = None
    prep_notes: LongNotes | None = None
    questions_to_ask: Questions | None = None
    reflection: LongNotes | None = None
    checklist: Checklist | None = None
    thank_you_sent_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> "InterviewRoundUpdate":
        bad = [f for f in _NON_NULLABLE_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        _unique_ids(self.checklist)
        return self


class InterviewRoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    kind: InterviewKind
    title: str | None
    scheduled_at: datetime | None
    duration_minutes: int | None
    format: InterviewFormat | None
    location: str | None
    interviewers: str | None
    state: InterviewState
    outcome: InterviewOutcome | None
    prep_notes: str | None
    questions_to_ask: str | None
    reflection: str | None
    checklist: list[ChecklistItem]
    thank_you_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InterviewRoundSummaryOut(InterviewRoundOut):
    """A round in a list: its fields plus the application's company and role,
    checklist progress and whether a thank-you is due."""

    company: str
    role_title: str
    checklist_done: int
    checklist_total: int
    thank_you_due: bool


class RoundContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    title: str | None


class RoundStoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class InterviewRoundDetailOut(InterviewRoundSummaryOut):
    """One round with its linked interviewers and planned stories."""

    contacts: list[RoundContactOut]
    stories: list[RoundStoryOut]


MAX_LINKS = 50


class RoundContactsIn(BaseModel):
    """The full set of linked contacts (replaces the current one)."""

    contact_ids: Annotated[list[int], Field(max_length=MAX_LINKS)]


class RoundStoriesIn(BaseModel):
    """The full set of linked stories (replaces the current one)."""

    story_ids: Annotated[list[int], Field(max_length=MAX_LINKS)]
