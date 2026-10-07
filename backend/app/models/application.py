import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApplicationStatus(str, enum.Enum):
    WISHLIST = "wishlist"
    APPLIED = "applied"
    PHONE_SCREEN = "phone_screen"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def enum_column(enum_cls: type[enum.Enum], name: str, **kwargs) -> SAEnum:
    """Postgres enum that stores the lowercase member *values* (not names)."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e], **kwargs)


class Application(Base):
    """One internship application and its tracked details."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    role_title: Mapped[str] = mapped_column(Text, nullable=False)
    date_applied: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_column(ApplicationStatus, "application_status"),
        nullable=False,
        default=ApplicationStatus.WISHLIST,
    )
    job_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_person: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_range: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "application_priority"), nullable=False, default=Priority.MEDIUM
    )
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    interview_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    google_doc_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
