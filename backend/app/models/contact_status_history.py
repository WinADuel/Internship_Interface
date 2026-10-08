from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import enum_column
from app.models.contact import ContactStatus


class ContactStatusHistory(Base):
    """One status transition of a contact; same shape as `status_history`."""

    __tablename__ = "contact_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status: Mapped[ContactStatus | None] = mapped_column(
        enum_column(ContactStatus, "contact_status"), nullable=True
    )
    new_status: Mapped[ContactStatus] = mapped_column(
        enum_column(ContactStatus, "contact_status"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
