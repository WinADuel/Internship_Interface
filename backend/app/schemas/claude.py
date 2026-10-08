"""Payloads exchanged with the scheduled Claude job (spec §13.5).

Everything Claude sends originates from arbitrary web pages, so every
string is stripped and length-capped and every list is size-capped."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.contact import EmailConfidence
from app.models.research_queue import QueueKind

MAX_BATCH = 25
MAX_SOURCES = 20


def _text(max_length: int, required: bool = False):
    return Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1 if required else 0, max_length=max_length),
    ]


class _ClaudeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class SourceIn(_ClaudeIn):
    label: _text(200)
    url: _text(2000)


class ContactIn(_ClaudeIn):
    queue_item_id: int
    name: _text(200, required=True)
    organization: _text(200, required=True)
    department: _text(200) | None = None
    title: _text(200) | None = None
    lab_name: _text(200) | None = None
    email: _text(320) | None = None
    email_confidence: EmailConfidence
    website_url: _text(2000) | None = None
    profile_url: _text(2000) | None = None
    relevance_note: _text(1000) | None = None
    research_summary: _text(5000) | None = None
    recent_work: _text(5000) | None = None
    sources: list[SourceIn] = Field(default_factory=list, max_length=MAX_SOURCES)
    draft_subject: _text(300) | None = None
    draft_body: _text(10000) | None = None


class ContactsBatchIn(_ClaudeIn):
    contacts: list[ContactIn] = Field(max_length=MAX_BATCH)


class FollowupIn(_ClaudeIn):
    contact_id: int
    followup_subject: _text(300, required=True)
    followup_body: _text(10000, required=True)


class FollowupsBatchIn(_ClaudeIn):
    followups: list[FollowupIn] = Field(max_length=MAX_BATCH)


class QueueResultIn(_ClaudeIn):
    result_note: _text(1000)


class IngestResultOut(BaseModel):
    created: int
    updated: int
    skipped: int


class WorkQueueItem(BaseModel):
    id: int
    kind: QueueKind
    request_text: str
    target_count: int


class KnownContact(BaseModel):
    name: str
    organization: str
    email: str | None


class FollowupNeeded(BaseModel):
    contact_id: int
    name: str
    organization: str
    draft_subject: str | None
    draft_body: str | None
    sent_at: datetime | None


class WorkOut(BaseModel):
    queue: list[WorkQueueItem]
    outreach_profile: str
    known_contacts: list[KnownContact]
    followups_needed: list[FollowupNeeded]
