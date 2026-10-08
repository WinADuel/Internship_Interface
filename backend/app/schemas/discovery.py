"""Request and response models for job discovery (Phase 2 spec §8).

Request fields are user input and response fields come from untrusted
sources, so every text field is capped (spec §9): company/title 300 chars,
each location 200, at most 20 locations, URLs 2000.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.posting import PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.schemas.settings import KeywordList
from app.services.discovery.filters import DiscoveryFilters
from app.services.discovery.parsers import (
    MAX_COMPANY,
    MAX_LOCATION,
    MAX_LOCATIONS,
    MAX_TITLE,
)
from app.services.discovery.urls import MAX_URL_LENGTH, safe_http_url

MAX_WATCH_NAME = 200
MAX_DISMISS_IDS = 500


def _one_line(value: str) -> str:
    """Control characters become spaces, whitespace runs collapse, ends trimmed."""
    return " ".join("".join(" " if ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F else c for c in value).split())


def _required_text(limit: int):
    def check(value: str) -> str:
        value = _one_line(value)
        if not value:
            raise ValueError("must not be empty")
        if len(value) > limit:
            raise ValueError(f"must be at most {limit} characters")
        return value

    return AfterValidator(check)


def _optional_text(limit: int):
    def check(value: str | None) -> str | None:
        if value is None:
            return None
        value = _one_line(value)
        if len(value) > limit:
            raise ValueError(f"must be at most {limit} characters")
        return value or None

    return AfterValidator(check)


def _http_url(value: str) -> str:
    safe = safe_http_url(value)
    if safe is None:
        raise ValueError("must be a web link starting with http or https")
    return safe


def _locations(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        value = _one_line(raw)
        if len(value) > MAX_LOCATION:
            raise ValueError(f"each location must be at most {MAX_LOCATION} characters")
        if value and value not in out:
            out.append(value)
    if len(out) > MAX_LOCATIONS:
        raise ValueError(f"at most {MAX_LOCATIONS} locations")
    return out


def _aware(value: datetime | None) -> datetime | None:
    # A date without a zone is read as UTC, like every other stored date.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# Raw length bounds keep validation cheap on hostile input; the validators
# above apply the real caps after cleaning.
_RawUrl = Annotated[str, Field(max_length=MAX_URL_LENGTH * 2)]
Company = Annotated[str, Field(max_length=MAX_COMPANY * 4), _required_text(MAX_COMPANY)]
Title = Annotated[str, Field(max_length=MAX_TITLE * 4), _required_text(MAX_TITLE)]
HttpUrl = Annotated[_RawUrl, AfterValidator(_http_url)]
Locations = Annotated[
    list[Annotated[str, Field(max_length=MAX_LOCATION * 4)]],
    Field(max_length=MAX_LOCATIONS * 4),
    AfterValidator(_locations),
]
AwareDatetime = Annotated[datetime | None, AfterValidator(_aware)]


# --- postings ----------------------------------------------------------------


class PostingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: PostingSource
    company: str
    title: str
    locations: list[str]
    url: str
    terms: list[str]
    category: str | None
    sponsorship: str | None
    date_posted: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closed: bool
    state: PostingState
    state_changed_at: datetime
    application_id: int | None
    watch_company_id: int | None
    claude_score: int | None
    claude_note: str | None


class PostingPage(BaseModel):
    items: list[PostingOut]
    total: int


class DismissAllIn(BaseModel):
    ids: list[int] = Field(max_length=MAX_DISMISS_IDS)


class DismissAllOut(BaseModel):
    dismissed: int


# --- paste a link ------------------------------------------------------------


class PasteIn(BaseModel):
    # Checked by the service, which answers a bad link with a readable message.
    url: _RawUrl


class PastePreviewOut(BaseModel):
    company: str
    title: str
    locations: list[str]
    url: str
    date_posted: datetime | None
    source: PostingSource


class PasteConfirmIn(BaseModel):
    url: HttpUrl
    company: Company
    title: Title
    locations: Locations = []
    date_posted: AwareDatetime = None


# --- watchlist ---------------------------------------------------------------


class WatchCompanyIn(BaseModel):
    careers_url: _RawUrl
    name: Annotated[str | None, Field(max_length=MAX_WATCH_NAME * 4), _optional_text(MAX_WATCH_NAME)] = None


class WatchCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ats: WatchAts
    board_token: str
    careers_url: str
    added_at: datetime
    last_checked_at: datetime | None
    last_error: str | None
    open_matches: int = 0

    @classmethod
    def build(cls, company: WatchCompany, open_matches: int) -> "WatchCompanyOut":
        out = cls.model_validate(company)
        out.open_matches = open_matches
        return out


# --- scan status and match count ---------------------------------------------


class ScanStartedOut(BaseModel):
    started: bool = True


class ScanStatusOut(BaseModel):
    last_scan_at: datetime | None
    last_scan_error: str | None
    scanning: bool
    inbox_count: int


class MatchCountIn(BaseModel):
    """Unsaved filter settings, named as in `SettingsUpdate`, for the live count."""

    discovery_terms: KeywordList = []
    discovery_categories: KeywordList = []
    discovery_include_keywords: KeywordList = []
    discovery_watchlist_keywords: KeywordList = []
    discovery_exclude_keywords: KeywordList = []
    discovery_locations: KeywordList = []
    discovery_hide_no_sponsorship: bool = False

    def to_filters(self) -> DiscoveryFilters:
        return DiscoveryFilters(
            terms=self.discovery_terms,
            categories=self.discovery_categories,
            include_keywords=self.discovery_include_keywords,
            watchlist_keywords=self.discovery_watchlist_keywords,
            exclude_keywords=self.discovery_exclude_keywords,
            locations=self.discovery_locations,
            hide_no_sponsorship=self.discovery_hide_no_sponsorship,
        )


class MatchCountOut(BaseModel):
    count: int
