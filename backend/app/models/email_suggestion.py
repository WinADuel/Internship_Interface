import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import enum_column


class SuggestionKind(str, enum.Enum):
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"
    INTERVIEW = "interview"
    ASSESSMENT = "assessment"
    OFFER = "offer"
    CONTACT_REPLY = "contact_reply"
    CONTACT_SENT = "contact_sent"
    NEW_APPLICATION = "new_application"


class EmailDirection(str, enum.Enum):
    INBOUND = "inbound"
    SENT = "sent"


class SuggestionState(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    STALE = "stale"
    AUTO_APPLIED = "auto_applied"


class EmailSuggestion(Base):
    """One matched email and the update it suggests (Phase 6 spec §5). Only
    matched emails are stored, and only their headers and Gmail's snippet,
    capped by the sync; never a body. Decided rows are deleted after 90 days.

    Gmail message ids are per mailbox, so a message is unique within its
    inbox (`gmail_account_id`, Phase 7 spec §4). Removing the inbox deletes
    its suggestions."""

    __tablename__ = "email_suggestions"
    __table_args__ = (
        Index("ix_email_suggestions_state_received_at", "state", "received_at"),
        UniqueConstraint("gmail_account_id", "gmail_message_id", name="uq_email_suggestions_account_message"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    gmail_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[EmailDirection] = mapped_column(
        enum_column(EmailDirection, "email_direction"), nullable=False
    )
    from_name: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    from_email: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    kind: Mapped[SuggestionKind] = mapped_column(
        enum_column(SuggestionKind, "email_suggestion_kind"), nullable=False
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    proposed_company: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[SuggestionState] = mapped_column(
        enum_column(SuggestionState, "email_suggestion_state"),
        nullable=False,
        default=SuggestionState.PENDING,
        server_default=SuggestionState.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
