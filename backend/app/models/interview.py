import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.application import Application, enum_column
from app.models.contact import Contact
from app.models.story import Story


class InterviewKind(str, enum.Enum):
    RECRUITER_SCREEN = "recruiter_screen"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    CASE = "case"
    ONSITE = "onsite"
    FINAL = "final"
    OTHER = "other"


class InterviewFormat(str, enum.Enum):
    VIDEO = "video"
    PHONE = "phone"
    IN_PERSON = "in_person"


class InterviewState(str, enum.Enum):
    SCHEDULED = "scheduled"
    DONE = "done"
    CANCELLED = "cancelled"


class InterviewOutcome(str, enum.Enum):
    WAITING = "waiting"
    PASSED = "passed"
    REJECTED = "rejected"


# Interviewers who are tracked contacts, so thank-you notes have an address.
interview_round_contacts = Table(
    "interview_round_contacts",
    Base.metadata,
    Column("round_id", ForeignKey("interview_rounds.id", ondelete="CASCADE"), primary_key=True),
    Column("contact_id", ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
)

# Story-bank stories the user plans to tell in a round.
interview_round_stories = Table(
    "interview_round_stories",
    Base.metadata,
    Column("round_id", ForeignKey("interview_rounds.id", ondelete="CASCADE"), primary_key=True),
    Column("story_id", ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True),
)


class InterviewRound(Base):
    """One interview round of an application, with its prep page data
    (Phase 4 spec §3). The application's `interview_datetime` is derived
    from its rounds by `interview_service`."""

    __tablename__ = "interview_rounds"
    __table_args__ = (Index("ix_interview_rounds_state_scheduled_at", "state", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[InterviewKind] = mapped_column(
        enum_column(InterviewKind, "interview_kind"),
        nullable=False,
        default=InterviewKind.OTHER,
        server_default=InterviewKind.OTHER.value,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[InterviewFormat | None] = mapped_column(
        enum_column(InterviewFormat, "interview_format"), nullable=True
    )
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    interviewers: Mapped[str | None] = mapped_column(String(500), nullable=True)
    state: Mapped[InterviewState] = mapped_column(
        enum_column(InterviewState, "interview_state"),
        nullable=False,
        default=InterviewState.SCHEDULED,
        server_default=InterviewState.SCHEDULED.value,
    )
    outcome: Mapped[InterviewOutcome | None] = mapped_column(
        enum_column(InterviewOutcome, "interview_outcome"), nullable=True
    )
    prep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    questions_to_ask: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A list of {"id": str, "label": str, "done": bool}.
    checklist: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    thank_you_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Read-only: rounds are created against an application id, never moved.
    application: Mapped[Application] = relationship(viewonly=True)
    contacts: Mapped[list[Contact]] = relationship(
        secondary=interview_round_contacts, order_by=Contact.id, passive_deletes=True
    )
    stories: Mapped[list[Story]] = relationship(
        secondary=interview_round_stories, order_by=Story.id, passive_deletes=True
    )
