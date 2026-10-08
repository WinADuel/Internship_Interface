import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import Priority, enum_column


class ContactKind(str, enum.Enum):
    PROFESSOR = "professor"
    COMPANY = "company"


class EmailConfidence(str, enum.Enum):
    FOUND = "found"
    PATTERN_GUESS = "pattern_guess"
    NOT_FOUND = "not_found"


class ContactStatus(str, enum.Enum):
    TO_CONTACT = "to_contact"
    SENT = "sent"
    FOLLOWED_UP = "followed_up"
    REPLIED = "replied"
    MEETING = "meeting"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class ContactOrigin(str, enum.Enum):
    CLAUDE = "claude"
    MANUAL = "manual"


class Contact(Base):
    """A professor or company person the user may reach out to (spec §13.2)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ContactKind] = mapped_column(enum_column(ContactKind, "contact_kind"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    organization: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    lab_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_confidence: Mapped[EmailConfidence] = mapped_column(
        enum_column(EmailConfidence, "email_confidence"),
        nullable=False,
        default=EmailConfidence.NOT_FOUND,
    )
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    relevance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    draft_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    followup_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    draft_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ContactStatus] = mapped_column(
        enum_column(ContactStatus, "contact_status"),
        nullable=False,
        default=ContactStatus.TO_CONTACT,
    )
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reuses the existing application_priority PG enum type (created in 0002);
    # migration 0004 references it with create_type=False.
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "application_priority"),
        nullable=False,
        default=Priority.MEDIUM,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meeting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nudge_snoozed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[ContactOrigin] = mapped_column(
        enum_column(ContactOrigin, "contact_origin"),
        nullable=False,
        default=ContactOrigin.MANUAL,
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
