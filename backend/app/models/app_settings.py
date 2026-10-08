from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSettings(Base):
    """Single-row (id = 1) app-wide settings for outreach (spec §13.2)."""

    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="app_settings_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, autoincrement=False)
    outreach_profile: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    nudge_unsent_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    nudge_followup_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    nudge_gone_quiet_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    nudge_replied_stale_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14, server_default="14"
    )
    claude_job_max_items: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    backup_sheet_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sheet_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sheet_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
