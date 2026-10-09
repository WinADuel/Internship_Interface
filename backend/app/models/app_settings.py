from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Phase 2 spec §3 defaults. Each list is both the Python default (a fresh copy
# per row) and the column's server default.
DEFAULT_LIST_URLS = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
)
DEFAULT_TERMS = ("Summer 2027",)
DEFAULT_CATEGORIES = ("Software", "AI/ML/Data")
DEFAULT_WATCHLIST_KEYWORDS = ("intern", "internship", "co-op")
DEFAULT_EXCLUDE_KEYWORDS = ("senior", "staff", "principal", "phd")


def _text_array_literal(values: tuple[str, ...]) -> str:
    """A Postgres `text[]` literal, e.g. `'{"a","b"}'::text[]`. Values are
    module constants; quotes, backslashes, braces and commas are refused."""
    if any(c in v for v in values for c in "\"\\'{},"):
        raise ValueError(f"unsafe array default: {values!r}")
    return "'{" + ",".join(f'"{v}"' for v in values) + "}'::text[]"


def _text_array(values: tuple[str, ...]):
    """Column kwargs for a NOT NULL text[] defaulting to `values`."""
    return dict(
        nullable=False,
        default=lambda: list(values),
        server_default=text(_text_array_literal(values)),
    )


class AppSettings(Base):
    """Single-row (id = 1) app-wide settings: outreach (spec §13.2) and job discovery (Phase 2 spec §3)."""

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

    # Job discovery (Phase 2).
    discovery_list_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(DEFAULT_LIST_URLS))
    discovery_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(DEFAULT_TERMS))
    discovery_categories: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(DEFAULT_CATEGORIES))
    discovery_include_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    discovery_watchlist_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), **_text_array(DEFAULT_WATCHLIST_KEYWORDS)
    )
    discovery_exclude_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), **_text_array(DEFAULT_EXCLUDE_KEYWORDS)
    )
    discovery_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    discovery_hide_no_sponsorship: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    discovery_scan_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default="6")
    # List URL -> ETag of the last download (server-owned, not exposed by the API).
    discovery_list_etags: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Inbox ranking preferences (Phase 5 spec §3). `ranking_updated_at` moves
    # whenever a preference list changes, which makes older Claude scores stale.
    ranking_role_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_skill_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_preferred_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_preferred_companies: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_avoid_companies: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_dealbreaker_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), **_text_array(()))
    ranking_claude_daily_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40, server_default="40"
    )
    ranking_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Database backups (Phase 3 spec §4.4): last success and last error of the
    # local dump and of the off-site copy. An error is cleared by the next success.
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_offsite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_offsite_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Gmail sync (Phase 6 spec §5). Off until the owner turns it on. The
    # cursor is the newest Gmail `internalDate` (ms) fully processed; it is
    # server-owned and not exposed by the API.
    gmail_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    gmail_sync_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    gmail_lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    gmail_auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    gmail_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmail_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_history_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
