"""Source fetchers for job discovery (Phase 2 spec §2).

Each fetcher reads one source through `DiscoveryHttp` and hands back parsed
postings; nothing here touches the database. Board API URLs are built only
from a token that passes the same checks as `urls.parse_board_url`, so a
tampered `watch_companies` row can never steer a request to another host or
path.

`fetch_list` and `fetch_board` never raise for a source that is down: they
return a `SourceResult` with `error` set, so one broken source never stops
the others (spec §5). `fetch_pasted` raises `DiscoveryFetchError` with a
message meant for the person who pasted the link.
"""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.models.app_settings import DEFAULT_LIST_URLS
from app.models.posting import PostingSource
from app.models.watch_company import WatchAts, WatchCompany
from app.services.discovery.http import (
    DEFAULT_TIMEOUT,
    LIST_MAX_BYTES,
    LIST_TIMEOUT,
    PAGE_MAX_BYTES,
    DiscoveryFetchError,
    DiscoveryHttp,
)
from app.services.discovery.parsers import (
    MAX_SOURCE_KEY,
    PastedDetails,
    PostingIn,
    clean_text,
    find_ashby_job,
    parse_ashby_board,
    parse_greenhouse_board,
    parse_greenhouse_job,
    parse_html_posting,
    parse_lever_board,
    parse_lever_job,
    parse_listings,
    parse_workday_job_detail,
    parse_workday_page,
)
from app.services.discovery.urls import (
    BoardRef,
    board_careers_url,
    parse_job_url,
    safe_http_url,
)

LIST_SOURCE_BY_URL: dict[str, PostingSource] = {
    DEFAULT_LIST_URLS[0]: PostingSource.SIMPLIFY,
    DEFAULT_LIST_URLS[1]: PostingSource.VANSHB03,
}
_LIST_NAMES = {
    PostingSource.SIMPLIFY: "Simplify list",
    PostingSource.VANSHB03: "vanshb03 list",
}

WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PER_KEYWORD = 200
# Seconds between two Workday page requests. Workday is the only source read
# with several requests per company, so this is where a scan could look like
# a hammering client.
WORKDAY_PAGE_PAUSE = 0.5

_NAME_MAX = 200
_ERROR_MAX = 500
_KEY_PREFIX_LENGTH = 10
_BAD_SHAPE = "unexpected response format"

_GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_LEVER_API = "https://api.lever.co/v0/postings/{token}"
_ASHBY_API = (
    "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
)


@dataclass
class SourceResult:
    name: str
    postings: list[PostingIn]
    # True: `postings` is the source's full current set, so postings it no
    # longer lists may be marked closed.
    complete: bool
    not_modified: bool = False
    etag: str | None = None
    # One line, "<name>: <reason>"; never a response body.
    error: str | None = None
    # Custom (LIST) sources only: every source_key starts with "<prefix>:",
    # so closing can be scoped to this one list.
    key_prefix: str | None = None
    # The source the postings belong to. Set on complete results, so ingest
    # can close a source's postings even when the result is empty.
    source: PostingSource | None = None


# --- helpers -----------------------------------------------------------------


def _failed(name: str, reason: object, key_prefix: str | None = None) -> SourceResult:
    error = clean_text(f"{name}: {reason}", _ERROR_MAX)
    return SourceResult(name, [], complete=False, error=error, key_prefix=key_prefix)


def list_source(url: str) -> PostingSource:
    return LIST_SOURCE_BY_URL.get(url, PostingSource.LIST)


def list_key_prefix(url: str) -> str:
    """A short, stable tag for a custom list URL, put in front of its keys so
    two custom lists never share a (source, source_key)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:_KEY_PREFIX_LENGTH]


def _list_name(url: str, source: PostingSource) -> str:
    if source in _LIST_NAMES:
        return _LIST_NAMES[source]
    try:
        parts = urlsplit(url)
        where = f"{parts.hostname or ''}{parts.path}"
    except ValueError:
        where = "invalid url"
    return clean_text(f"List {where}", _NAME_MAX)


def list_name(url: str) -> str:
    """How a list is named in errors (the prefix of `SourceResult.error`)."""
    return _list_name(url, list_source(url))


def company_name(company: WatchCompany) -> str:
    """How a watched company is named in errors."""
    return clean_text(company.name, _NAME_MAX) or "Watched company"


def _board_api_url(ats: WatchAts, token: str) -> str:
    """The board's job-list API URL. Raises ValueError for a malformed token."""
    board_careers_url(BoardRef(ats, token))  # validates the token
    if ats is WatchAts.GREENHOUSE:
        return _GREENHOUSE_API.format(token=token)
    if ats is WatchAts.LEVER:
        return _LEVER_API.format(token=token) + "?mode=json"
    if ats is WatchAts.ASHBY:
        return _ASHBY_API.format(token=token)
    raise ValueError("not a single-request board")


def _workday_parts(token: str) -> tuple[str, str, str]:
    """(host, tenant, site). Raises ValueError for a malformed token."""
    board_careers_url(BoardRef(WatchAts.WORKDAY, token))  # validates the token
    host, tenant, site = token.split("/")
    return host, tenant, site


def _search_texts(keywords: list[str]) -> list[str]:
    """The keywords to search a Workday board for, in order: trimmed, with
    blanks, case-insensitive duplicates and keywords another keyword already
    covers dropped. A Workday search matches a substring, so "internship"
    returns a subset of what "intern" returns: searching both only costs
    round trips. The shorter keyword wins, and the original order is kept."""
    texts: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        text = keyword.strip() if isinstance(keyword, str) else ""
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            texts.append(text)
    kept: list[str] = []
    # Shortest first, so a keyword is only ever dropped in favour of a shorter
    # one; the result is then put back in the caller's order.
    for text in sorted(texts, key=len):
        folded = text.casefold()
        if not any(k.casefold() in folded for k in kept):
            kept.append(text)
    # No keywords: one empty search, i.e. the newest postings on the board.
    return [t for t in texts if t in kept] or [""]


# --- community lists ---------------------------------------------------------


def fetch_list(http: DiscoveryHttp, url: str, etag: str | None) -> SourceResult:
    """One community `listings.json` (spec §2a), as a conditional GET."""
    source = list_source(url)
    name = _list_name(url, source)
    prefix = list_key_prefix(url) if source is PostingSource.LIST else None
    try:
        result = http.get_json(
            url, etag=etag, max_bytes=LIST_MAX_BYTES, timeout=LIST_TIMEOUT
        )
    except DiscoveryFetchError as exc:
        return _failed(name, exc, prefix)
    if result.status == 304:
        return SourceResult(
            name,
            [],
            complete=False,
            not_modified=True,
            etag=result.etag or etag,
            key_prefix=prefix,
            # Set so the scan can mark this list's postings seen again.
            source=source,
        )
    data = result.data
    if not isinstance(data, list):
        return _failed(name, _BAD_SHAPE, prefix)
    postings = parse_listings(data, source)
    if prefix is not None:
        for posting in postings:
            posting.source_key = f"{prefix}:{posting.source_key}"
        postings = [p for p in postings if len(p.source_key) <= MAX_SOURCE_KEY]
    if data and not postings:
        # Rows came back but none could be read: the format changed. Treat it
        # as a failure, or every posting from this list would be closed.
        return _failed(name, _BAD_SHAPE, prefix)
    return SourceResult(
        name,
        postings,
        complete=True,
        etag=result.etag,
        key_prefix=prefix,
        source=source,
    )


# --- watched boards ----------------------------------------------------------


def _fetch_single_request_board(
    http: DiscoveryHttp, company: WatchCompany, name: str
) -> SourceResult:
    api_url = _board_api_url(company.ats, company.board_token)
    result = http.get_json(api_url, max_bytes=LIST_MAX_BYTES, timeout=DEFAULT_TIMEOUT)
    data = result.data
    token = company.board_token
    rows: Any
    if company.ats is WatchAts.LEVER:
        rows = data
        parse = parse_lever_board
    else:
        rows = data.get("jobs") if isinstance(data, dict) else None
        parse = (
            parse_greenhouse_board
            if company.ats is WatchAts.GREENHOUSE
            else parse_ashby_board
        )
    if not isinstance(rows, list):
        return _failed(name, _BAD_SHAPE)
    postings = parse(data, token, name)
    expected = rows
    if company.ats is WatchAts.ASHBY:  # unlisted jobs are skipped on purpose
        expected = [
            r for r in rows if not (isinstance(r, dict) and r.get("isListed") is False)
        ]
    if expected and not postings:
        return _failed(name, _BAD_SHAPE)
    return SourceResult(
        name, postings, complete=True, source=PostingSource(company.ats.value)
    )


def _fetch_workday(
    http: DiscoveryHttp,
    company: WatchCompany,
    name: str,
    keywords: list[str],
    now: datetime | None,
    pause: Callable[[float], None],
) -> SourceResult:
    host, tenant, site = _workday_parts(company.board_token)
    api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    merged: dict[str, PostingIn] = {}
    requests = 0
    for text in _search_texts(keywords):
        offset = 0
        total: int | None = None
        while offset < WORKDAY_MAX_PER_KEYWORD:
            if requests:
                pause(WORKDAY_PAGE_PAUSE)
            requests += 1
            body = {
                "appliedFacets": {},
                "limit": WORKDAY_PAGE_SIZE,
                "offset": offset,
                "searchText": text,
            }
            data = http.post_json(
                api_url, body, max_bytes=LIST_MAX_BYTES, timeout=DEFAULT_TIMEOUT
            ).data
            rows = data.get("jobPostings") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return _failed(name, _BAD_SHAPE)
            postings, page_total = parse_workday_page(
                data, host, tenant, site, name, now=now
            )
            if total is None:
                # Only the first page's total is trustworthy; later pages may report 0.
                total = page_total
            for posting in postings:
                merged.setdefault(posting.source_key, posting)
            offset += WORKDAY_PAGE_SIZE
            if not rows or offset >= total:
                break
    # A keyword search is not the whole board, so nothing may be closed from it.
    return SourceResult(name, list(merged.values()), complete=False)


def fetch_board(
    http: DiscoveryHttp,
    company: WatchCompany,
    keywords: list[str],
    *,
    now: datetime | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> SourceResult:
    """One watched company's board (spec §2b). Greenhouse, Lever and Ashby:
    one GET of the whole board (`complete=True`). Workday: a search per
    keyword (`complete=False`), with `pause` between pages. `now` dates
    Workday's "Posted N Days Ago"."""
    name = company_name(company)
    try:
        if company.ats is WatchAts.WORKDAY:
            return _fetch_workday(http, company, name, keywords, now, pause)
        return _fetch_single_request_board(http, company, name)
    except ValueError:
        return _failed(name, "invalid board address")
    except DiscoveryFetchError as exc:
        return _failed(name, exc)


# --- pasted links ------------------------------------------------------------


def _readable(exc: DiscoveryFetchError) -> DiscoveryFetchError:
    reason = f"status {exc.status}" if exc.status is not None else str(exc)
    return DiscoveryFetchError(f"Couldn't read that page ({reason})", status=exc.status)


def _fetch_pasted_job(
    http: DiscoveryHttp, ref, now: datetime | None
) -> PastedDetails | None:
    def get(api_url: str, max_bytes: int = PAGE_MAX_BYTES) -> Any:
        return http.get_json(api_url, max_bytes=max_bytes, timeout=DEFAULT_TIMEOUT).data

    if ref.ats is WatchAts.GREENHOUSE:
        url = f"{_board_api_url(ref.ats, ref.token)}/{ref.job_id}"
        return parse_greenhouse_job(get(url), ref.token)
    if ref.ats is WatchAts.LEVER:
        board_careers_url(BoardRef(ref.ats, ref.token))  # validates the token
        return parse_lever_job(
            get(f"{_LEVER_API.format(token=ref.token)}/{ref.job_id}"), ref.token
        )
    if ref.ats is WatchAts.ASHBY:
        # Ashby has no public single-job endpoint: read the board, find the job.
        board = get(_board_api_url(ref.ats, ref.token), LIST_MAX_BYTES)
        return find_ashby_job(board, ref.job_id, ref.token)
    host, tenant, site = _workday_parts(ref.token)
    # Endpoint shape taken from public examples of Workday's career-page calls
    # (undocumented): verify it on the first real pasted Workday link.
    data = get(f"https://{host}/wday/cxs/{tenant}/{site}/{ref.job_id}")
    return parse_workday_job_detail(data, host, tenant, site, ref.job_id, now=now)


def fetch_pasted(
    http: DiscoveryHttp, url: str, *, now: datetime | None = None
) -> PastedDetails:
    """Details of a pasted posting link (spec §2c): a Greenhouse, Lever, Ashby
    or Workday job link is read from the board's API; any other page is
    downloaded once (SSRF-guarded by `get_page`) and its JobPosting data read.
    Raises `DiscoveryFetchError` with a message for the user."""
    if not isinstance(url, str) or safe_http_url(url) is None:
        raise DiscoveryFetchError(
            "That isn't a web link: it must start with http or https"
        )
    url = url.strip()
    ref = parse_job_url(url)
    try:
        if ref is None:
            page = http.get_page(url, max_bytes=PAGE_MAX_BYTES, timeout=DEFAULT_TIMEOUT)
            # Key on the pasted URL, not the redirect target: paste-confirm
            # keys the same way, so a preview and its confirm agree.
            return parse_html_posting(page.text or "", url)
        details = _fetch_pasted_job(http, ref, now)
    except DiscoveryFetchError as exc:
        raise _readable(exc) from None
    except ValueError:
        # A recognized link whose token fails validation; parse_job_url
        # already checks tokens, so this is defensive.
        raise DiscoveryFetchError("Couldn't read that link") from None
    if details is None:
        raise DiscoveryFetchError(
            "Couldn't find that job on its job board (it may have been taken down)"
        )
    return details
