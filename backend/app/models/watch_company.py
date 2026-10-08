import enum
from datetime import datetime

from sqlalchemy import DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import enum_column


class WatchAts(str, enum.Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"


class WatchCompany(Base):
    """A company whose public job board the scanner reads (Phase 2 spec §2b, §3)."""

    __tablename__ = "watch_companies"
    __table_args__ = (UniqueConstraint("ats", "board_token", name="uq_watch_companies_ats_board_token"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ats: Mapped[WatchAts] = mapped_column(enum_column(WatchAts, "watch_ats"), nullable=False)
    # Greenhouse/Lever/Ashby: the board token. Workday: "<host>/<tenant>/<site>".
    board_token: Mapped[str] = mapped_column(Text, nullable=False)
    careers_url: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # One line, never a response body.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
