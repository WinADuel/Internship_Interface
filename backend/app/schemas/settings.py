from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_LIST_ITEMS = 30
MAX_LIST_ITEM_LENGTH = 100
MAX_LIST_URLS = 10
MAX_LIST_URL_LENGTH = 500
# Ranking preference lists (Phase 5 spec §3).
MAX_RANKING_ITEM_LENGTH = 60
MAX_CLAUDE_DAILY_LIMIT = 150


def _normalize(items: list[str], *, max_items: int, max_length: int) -> list[str]:
    """Strip each item, drop empty ones, and drop case-insensitive duplicates
    (the first spelling wins); then enforce the item length and count caps."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = raw.strip()
        if not item or item.casefold() in seen:
            continue
        if len(item) > max_length:
            raise ValueError(f"each item must be at most {max_length} characters")
        seen.add(item.casefold())
        out.append(item)
    if len(out) > max_items:
        raise ValueError(f"at most {max_items} items")
    return out


def _keyword_list(items: list[str]) -> list[str]:
    return _normalize(items, max_items=MAX_LIST_ITEMS, max_length=MAX_LIST_ITEM_LENGTH)


def _ranking_list(items: list[str]) -> list[str]:
    return _normalize(items, max_items=MAX_LIST_ITEMS, max_length=MAX_RANKING_ITEM_LENGTH)


def _url_list(items: list[str]) -> list[str]:
    urls = _normalize(items, max_items=MAX_LIST_URLS, max_length=MAX_LIST_URL_LENGTH)
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise ValueError("each list URL must start with https://")
    return urls


KeywordList = Annotated[list[str], AfterValidator(_keyword_list)]
UrlList = Annotated[list[str], AfterValidator(_url_list)]
RankingList = Annotated[list[str], AfterValidator(_ranking_list)]


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outreach_profile: str
    nudge_unsent_days: int
    nudge_followup_days: int
    nudge_gone_quiet_days: int
    nudge_replied_stale_days: int
    claude_job_max_items: int
    backup_sheet_id: str | None
    last_sheet_sync_at: datetime | None
    last_sheet_sync_error: str | None
    discovery_list_urls: list[str]
    discovery_terms: list[str]
    discovery_categories: list[str]
    discovery_include_keywords: list[str]
    discovery_watchlist_keywords: list[str]
    discovery_exclude_keywords: list[str]
    discovery_locations: list[str]
    discovery_hide_no_sponsorship: bool
    discovery_scan_hours: int
    last_scan_at: datetime | None
    last_scan_error: str | None
    ranking_role_keywords: list[str]
    ranking_skill_keywords: list[str]
    ranking_preferred_locations: list[str]
    ranking_preferred_companies: list[str]
    ranking_avoid_companies: list[str]
    ranking_dealbreaker_keywords: list[str]
    ranking_claude_daily_limit: int
    ranking_updated_at: datetime | None
    # Computed from the stored Google token, not settings columns.
    google_connected: bool = False
    gmail_granted: bool = False


class SettingsUpdate(BaseModel):
    outreach_profile: str | None = Field(default=None, max_length=5000)
    nudge_unsent_days: int | None = Field(default=None, ge=1, le=90)
    nudge_followup_days: int | None = Field(default=None, ge=1, le=90)
    nudge_gone_quiet_days: int | None = Field(default=None, ge=1, le=90)
    nudge_replied_stale_days: int | None = Field(default=None, ge=1, le=90)
    claude_job_max_items: int | None = Field(default=None, ge=1, le=25)
    discovery_list_urls: UrlList | None = None
    discovery_terms: KeywordList | None = None
    discovery_categories: KeywordList | None = None
    discovery_include_keywords: KeywordList | None = None
    discovery_watchlist_keywords: KeywordList | None = None
    discovery_exclude_keywords: KeywordList | None = None
    discovery_locations: KeywordList | None = None
    discovery_hide_no_sponsorship: bool | None = None
    discovery_scan_hours: int | None = Field(default=None, ge=1, le=48)
    ranking_role_keywords: RankingList | None = None
    ranking_skill_keywords: RankingList | None = None
    ranking_preferred_locations: RankingList | None = None
    ranking_preferred_companies: RankingList | None = None
    ranking_avoid_companies: RankingList | None = None
    ranking_dealbreaker_keywords: RankingList | None = None
    ranking_claude_daily_limit: int | None = Field(default=None, ge=0, le=MAX_CLAUDE_DAILY_LIMIT)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "SettingsUpdate":
        # Every column is NOT NULL; omitted means unchanged.
        bad = [f for f in self.model_fields_set if getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(sorted(bad))} cannot be null")
        return self


class SheetSyncOut(BaseModel):
    ok: bool
    last_sheet_sync_at: datetime | None
    last_sheet_sync_error: str | None
    sheet_url: str | None
