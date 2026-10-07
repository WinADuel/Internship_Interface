from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import ApplicationStatus, enum_column


class StatusHistory(Base):
    """One status transition of an application; `old_status` is null for the
    initial entry. Sole source for the dashboard's "What's New" feed."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status: Mapped[ApplicationStatus | None] = mapped_column(
        enum_column(ApplicationStatus, "application_status"), nullable=True
    )
    new_status: Mapped[ApplicationStatus] = mapped_column(
        enum_column(ApplicationStatus, "application_status"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
