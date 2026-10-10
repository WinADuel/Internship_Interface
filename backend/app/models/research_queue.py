import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import enum_column


class QueueKind(str, enum.Enum):
    PROFESSOR_PERSON = "professor_person"
    PROFESSOR_SEARCH = "professor_search"
    COMPANY_CONTACTS = "company_contacts"
    INTERVIEW_BRIEF = "interview_brief"  # Phase 4: a company brief for an interview


class QueueState(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class ResearchQueueItem(Base):
    """A research request for the scheduled Claude job (spec §13.2)."""

    __tablename__ = "research_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[QueueKind] = mapped_column(enum_column(QueueKind, "queue_kind"), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    state: Mapped[QueueState] = mapped_column(
        enum_column(QueueState, "queue_state"), nullable=False, default=QueueState.PENDING
    )
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
