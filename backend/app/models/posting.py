import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import enum_column


class PostingSource(str, enum.Enum):
    SIMPLIFY = "simplify"
    VANSHB03 = "vanshb03"
    LIST = "list"  # any other configured list URL
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    PASTED = "pasted"


class PostingState(str, enum.Enum):
    NEW = "new"
    SAVED = "saved"
    DISMISSED = "dismissed"
    APPLIED = "applied"


class Posting(Base):
    """One discovered job posting (Phase 2 spec §3). Every text field comes
    from an untrusted source; parsers cap lengths before rows reach here."""

    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_postings_source_source_key"),
        # Cross-source de-duplication matches company + title case-insensitively.
        Index("ix_postings_lower_company_lower_title", func.lower(text("company")), func.lower(text("title"))),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[PostingSource] = mapped_column(
        enum_column(PostingSource, "posting_source"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    terms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    sponsorship: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    state: Mapped[PostingState] = mapped_column(
        enum_column(PostingState, "posting_state"),
        nullable=False,
        default=PostingState.NEW,
        server_default=PostingState.NEW.value,
        index=True,
    )
    # Orders the Dismissed tab ("most recent 200").
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    watch_company_id: Mapped[int | None] = mapped_column(
        ForeignKey("watch_companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Reserved for Claude ranking (spec §6).
    claude_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claude_note: Mapped[str | None] = mapped_column(Text, nullable=True)
