"""Parsers for job discovery sources (Phase 2 spec §2).

Pure functions: no network, no database. Every input here is untrusted
(community lists, public job-board APIs, pages a user pasted), so each parser
accepts any JSON-ish value, caps every string it keeps, and drops rows
without a safe http(s) URL, a title or a company instead of raising.

Board response shapes come from each vendor's public docs; see
tests/fixtures/discovery/README.md for what has been checked against live data.
"""

import html
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from app.models.posting import PostingSource
from app.services.discovery.urls import normalize_url, safe_http_url

MAX_COMPANY = 300
MAX_TITLE = 300
MAX_LOCATION = 200
MAX_LOCATIONS = 20
MAX_TERM = 100
MAX_TERMS = 20
MAX_LABEL = 100  # category, sponsorship
MAX_SOURCE_KEY = 500  # longer keys are dropped, not truncated (truncation could collide)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# Simplify still carries some rows under older, longer category names.
# Mapping them keeps the category filter (spec §4) working on those rows.
_CATEGORY_ALIASES = {
    "software engineering": "Software",
    "data science, ai & machine learning": "AI/ML/Data",
    "hardware engineering": "Hardware",
    "quantitative finance": "Quant",
    "product management": "Product",
}

# Unix seconds beyond 2100-01-01 are not a posting date (likely milliseconds).
_MAX_UNIX_SECONDS = 4_102_444_800

_WORKDAY_POSTED_RE = re.compile(
    r"^posted\s+(?:(today)|(yesterday)|(\d{1,3})\+?\s+days?\s+ago)$", re.IGNORECASE
)
_WORKDAY_MAX_DAYS = 365
_WORKDAY_LOCATIONS_COUNT_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)
# RFC 3986 path characters, minus anything that could change the URL's meaning.
_WORKDAY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~%!$&'()*+,;=:@-]+$")

# Second-level labels under a two-letter country TLD (acme.co.uk, acme.com.au).
_SECOND_LEVEL_LABELS = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or"})
_HOST_PREFIX_LABELS = frozenset({"www", "careers", "jobs", "job", "apply", "boards"})

_JSONLD_MAX_DEPTH = 6


@dataclass
class PostingIn:
    """One posting from a list or board, ready for ingest (spec §3)."""

    source: PostingSource
    source_key: str
    company: str
    title: str
    locations: list[str]
    url: str
    terms: list[str]
    category: str | None
    sponsorship: str | None
    date_posted: datetime | None
    # False when the source marks the row inactive or hidden; ingest uses it
    # to close postings it already has and to ignore new ones.
    active: bool


@dataclass
class PastedDetails:
    """What a pasted link resolved to, shown as an editable preview (spec §2c).
    For pages not on a known board, source is PASTED and source_key the url_key."""

    company: str
    title: str
    locations: list[str]
    date_posted: datetime | None
    source: PostingSource
    source_key: str


# --- small helpers -----------------------------------------------------------


def clean_text(value: Any, limit: int) -> str:
    """`value` as one line of plain text at most `limit` chars: non-strings
    become "", control characters become spaces, whitespace runs collapse."""
    if not isinstance(value, str):
        return ""
    # Bound the work on hostile input before cleaning.
    value = _CONTROL_RE.sub(" ", value[: limit * 4 + 64])
    return " ".join(value.split())[:limit].rstrip()


def _optional_text(value: Any, limit: int) -> str | None:
    return clean_text(value, limit) or None


def _text_list(value: Any, item_limit: int, max_items: int) -> list[str]:
    """A cleaned, de-duplicated list of strings (a bare string counts as one)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = clean_text(item, item_limit)
        if text and text not in out:
            out.append(text)
            if len(out) == max_items:
                break
    return out


def _locations(value: Any) -> list[str]:
    return _text_list(value, MAX_LOCATION, MAX_LOCATIONS)


def _source_key(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    key = clean_text(value, MAX_SOURCE_KEY + 1)
    return key if key and len(key) <= MAX_SOURCE_KEY else None


def _lower_key(value: Any) -> Any:
    # Lever and Ashby ids are UUIDs; parse_job_url lowercases them, so the
    # board and paste paths must too or the same job gets two keys.
    return value.lower() if isinstance(value, str) else value


def _from_unix_seconds(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or not 0 < value <= _MAX_UNIX_SECONDS:
        return None
    return datetime.fromtimestamp(value, UTC)


def _from_unix_millis(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return _from_unix_seconds(value / 1000)


def _from_iso(value: Any) -> datetime | None:
    """An ISO 8601 date or datetime as an aware UTC datetime; naive values
    and bare dates are taken as UTC."""
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _midnight(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)


def company_from_token(token: str) -> str:
    """A display name from a board token or host label: "acme-robotics" ->
    "Acme Robotics", "openai" -> "Openai". Only first letters change."""
    words = [w for w in re.split(r"[-_\s]+", token) if w]
    return clean_text(" ".join(w[:1].upper() + w[1:] for w in words), MAX_COMPANY)


def _host_label(url: str) -> str:
    """The registrable-looking label of the URL's host ("jobs.acme.co.uk" -> "acme")."""
    try:
        host = (urlsplit(url).hostname or "").rstrip(".")
    except ValueError:
        return ""
    labels = [label for label in host.split(".") if label]
    while len(labels) > 2 and labels[0] in _HOST_PREFIX_LABELS:
        labels = labels[1:]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL_LABELS:
        return labels[-3]
    if len(labels) >= 2:
        return labels[-2]
    return labels[0] if labels else ""


def _dicts(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _make_posting(
    *,
    source: PostingSource,
    source_key: Any,
    company: Any,
    title: Any,
    url: Any,
    locations: list[str],
    date_posted: datetime | None,
    terms: list[str] | None = None,
    category: str | None = None,
    sponsorship: str | None = None,
    active: bool = True,
) -> PostingIn | None:
    """A PostingIn, or None when the URL is unsafe or a required field is empty."""
    safe_url = safe_http_url(url) if isinstance(url, str) else None
    key = _source_key(source_key)
    company_text = clean_text(company, MAX_COMPANY)
    title_text = clean_text(title, MAX_TITLE)
    if not (safe_url and key and company_text and title_text):
        return None
    return PostingIn(
        source=source,
        source_key=key,
        company=company_text,
        title=title_text,
        locations=locations,
        url=safe_url,
        terms=terms or [],
        category=category,
        sponsorship=sponsorship,
        date_posted=date_posted,
        active=active,
    )


# --- community lists ---------------------------------------------------------


def _category(value: Any) -> str | None:
    text = _optional_text(value, MAX_LABEL)
    if text is None:
        return None
    return _CATEGORY_ALIASES.get(text.lower(), text)


def _terms(row: dict) -> list[str]:
    terms = row.get("terms")
    if terms is not None:
        return _text_list(terms, MAX_TERM, MAX_TERMS)
    # vanshb03 has `season`: a bare season word ("Summer"), "Spring/Summer",
    # or the string "null".
    season = row.get("season")
    if not isinstance(season, str) or season.strip().lower() in ("", "null", "none", "n/a"):
        return []
    return _text_list(season.split("/"), MAX_TERM, MAX_TERMS)


def parse_listings(data: Any, source: PostingSource) -> list[PostingIn]:
    """Rows of a community `listings.json` (spec §2a). Inactive or hidden rows
    are returned with active=False so ingest can close postings it has."""
    if not isinstance(data, list):
        return []
    postings = []
    for row in data:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        key = row.get("id")
        if _source_key(key) is None and isinstance(url, str):
            key = normalize_url(url)
        posting = _make_posting(
            source=source,
            source_key=key,
            company=row.get("company_name"),
            title=row.get("title"),
            url=url,
            locations=_locations(row.get("locations")),
            date_posted=_from_unix_seconds(row.get("date_posted")),
            terms=_terms(row),
            category=_category(row.get("category")),
            sponsorship=_optional_text(row.get("sponsorship"), MAX_LABEL),
            active=row.get("active", True) is not False and row.get("is_visible", True) is not False,
        )
        if posting is not None:
            postings.append(posting)
    return postings


# --- Greenhouse --------------------------------------------------------------


def _greenhouse_fields(job: dict) -> tuple[list[str], datetime | None]:
    location = job.get("location")
    locations = _locations(location.get("name")) if isinstance(location, dict) else []
    date_posted = _from_iso(job.get("first_published")) or _from_iso(job.get("updated_at"))
    return locations, date_posted


def parse_greenhouse_board(data: Any, token: str, company: str) -> list[PostingIn]:
    """`GET boards-api.greenhouse.io/v1/boards/<token>/jobs` (spec §2b).
    Greenhouse job ids are global, so the id alone is the source key."""
    if not isinstance(data, dict):
        return []
    postings = []
    for job in _dicts(data.get("jobs")):
        locations, date_posted = _greenhouse_fields(job)
        posting = _make_posting(
            source=PostingSource.GREENHOUSE,
            source_key=job.get("id"),
            company=company,
            title=job.get("title"),
            url=job.get("absolute_url"),
            locations=locations,
            date_posted=date_posted,
        )
        if posting is not None:
            postings.append(posting)
    return postings


def parse_greenhouse_job(data: Any, token: str) -> PastedDetails | None:
    """`GET boards-api.greenhouse.io/v1/boards/<token>/jobs/<id>` for a pasted link."""
    if not isinstance(data, dict):
        return None
    key = _source_key(data.get("id"))
    title = clean_text(data.get("title"), MAX_TITLE)
    if not key or not title:
        return None
    locations, date_posted = _greenhouse_fields(data)
    return PastedDetails(
        company=clean_text(data.get("company_name"), MAX_COMPANY) or company_from_token(token),
        title=title,
        locations=locations,
        date_posted=date_posted,
        source=PostingSource.GREENHOUSE,
        source_key=key,
    )


# --- Lever -------------------------------------------------------------------


def _lever_locations(job: dict) -> list[str]:
    categories = job.get("categories")
    if not isinstance(categories, dict):
        return []
    return _locations(categories.get("allLocations")) or _locations(categories.get("location"))


def parse_lever_board(data: Any, token: str, company: str) -> list[PostingIn]:
    """`GET api.lever.co/v0/postings/<token>?mode=json` (spec §2b): a JSON array."""
    if not isinstance(data, list):
        return []
    postings = []
    for job in _dicts(data):
        posting = _make_posting(
            source=PostingSource.LEVER,
            source_key=_lower_key(job.get("id")),
            company=company,
            title=job.get("text"),
            url=job.get("hostedUrl"),
            locations=_lever_locations(job),
            date_posted=_from_unix_millis(job.get("createdAt")),
        )
        if posting is not None:
            postings.append(posting)
    return postings


def parse_lever_job(data: Any, token: str) -> PastedDetails | None:
    """`GET api.lever.co/v0/postings/<token>/<id>` for a pasted link. Lever's
    payload has no company name, so it comes from the token."""
    if not isinstance(data, dict):
        return None
    key = _source_key(_lower_key(data.get("id")))
    title = clean_text(data.get("text"), MAX_TITLE)
    if not key or not title:
        return None
    return PastedDetails(
        company=company_from_token(token),
        title=title,
        locations=_lever_locations(data),
        date_posted=_from_unix_millis(data.get("createdAt")),
        source=PostingSource.LEVER,
        source_key=key,
    )


# --- Ashby -------------------------------------------------------------------


def _ashby_locations(job: dict) -> list[str]:
    raw = [job.get("location")]
    raw += [item.get("location") for item in _dicts(job.get("secondaryLocations"))]
    return _locations(raw)


def parse_ashby_board(data: Any, token: str, company: str) -> list[PostingIn]:
    """`GET api.ashbyhq.com/posting-api/job-board/<token>` (spec §2b).
    Jobs with isListed == false are skipped."""
    if not isinstance(data, dict):
        return []
    postings = []
    for job in _dicts(data.get("jobs")):
        if job.get("isListed") is False:
            continue
        posting = _make_posting(
            source=PostingSource.ASHBY,
            source_key=_lower_key(job.get("id")),
            company=company,
            title=job.get("title"),
            url=job.get("jobUrl"),
            locations=_ashby_locations(job),
            date_posted=_from_iso(job.get("publishedAt")),
        )
        if posting is not None:
            postings.append(posting)
    return postings


def find_ashby_job(board_data: Any, job_id: str, token: str) -> PastedDetails | None:
    """The job `job_id` from an Ashby board response (Ashby has no public
    single-job endpoint). Unlisted jobs are found too: the user has the link."""
    if not isinstance(board_data, dict) or not isinstance(job_id, str):
        return None
    wanted = job_id.lower()
    for job in _dicts(board_data.get("jobs")):
        key = job.get("id")
        if not isinstance(key, str) or key.lower() != wanted:
            continue
        title = clean_text(job.get("title"), MAX_TITLE)
        source_key = _source_key(key.lower())
        if not title or not source_key:
            return None
        return PastedDetails(
            company=company_from_token(token),
            title=title,
            locations=_ashby_locations(job),
            date_posted=_from_iso(job.get("publishedAt")),
            source=PostingSource.ASHBY,
            source_key=source_key,
        )
    return None


# --- Workday -----------------------------------------------------------------


def workday_source_key(host: str, tenant: str, site: str, external_path: str) -> str:
    """Workday's externalPath is only unique within one tenant's site, so the
    key carries the board token ("<host>/<tenant>/<site>") in front of it."""
    return f"{host}/{tenant}/{site}/{external_path.lstrip('/')}"


def parse_workday_posted_on(text: Any, now: datetime) -> datetime | None:
    """Workday's `postedOn`: "Posted Today", "Posted Yesterday", "Posted N Days
    Ago" or "Posted 30+ Days Ago" -> midnight UTC of that day; else None."""
    if not isinstance(text, str):
        return None
    match = _WORKDAY_POSTED_RE.match(" ".join(text.split()))
    if match is None:
        return None
    today, yesterday, days = match.groups()
    if today:
        offset = 0
    elif yesterday:
        offset = 1
    else:
        offset = int(days)
        if offset > _WORKDAY_MAX_DAYS:
            return None
    return _midnight(now.astimezone(UTC) - timedelta(days=offset))


def _safe_workday_path(path: Any) -> str | None:
    """`path` if it is a plain "/job/..." path that cannot leave the board."""
    if not isinstance(path, str) or len(path) > MAX_SOURCE_KEY or not path.startswith("/job/"):
        return None
    segments = path[1:].split("/")
    for segment in segments:
        if segment in ("", ".", "..") or not _WORKDAY_SEGMENT_RE.match(segment):
            return None
    return path


def _workday_locations(value: Any) -> list[str]:
    # A multi-location job shows only a count ("2 Locations"); that is not a place.
    locations = _locations(value)
    return [loc for loc in locations if not _WORKDAY_LOCATIONS_COUNT_RE.match(loc)]


def parse_workday_page(
    data: Any,
    host: str,
    tenant: str,
    site: str,
    company: str,
    *,
    now: datetime | None = None,
) -> tuple[list[PostingIn], int]:
    """One page of `POST https://<host>/wday/cxs/<tenant>/<site>/jobs` (spec §2b):
    (postings, total). `total` is whatever the page reports (0 if missing)."""
    if not isinstance(data, dict):
        return [], 0
    now = now or datetime.now(UTC)
    total = data.get("total")
    total = total if isinstance(total, int) and not isinstance(total, bool) and total > 0 else 0
    postings = []
    for job in _dicts(data.get("jobPostings")):
        path = _safe_workday_path(job.get("externalPath"))
        if path is None:
            continue
        posting = _make_posting(
            source=PostingSource.WORKDAY,
            source_key=workday_source_key(host, tenant, site, path),
            company=company,
            title=job.get("title"),
            url=f"https://{host}/{site}{path}",
            locations=_workday_locations(job.get("locationsText")),
            date_posted=parse_workday_posted_on(job.get("postedOn"), now),
        )
        if posting is not None:
            postings.append(posting)
    return postings, total


def parse_workday_job_detail(
    data: Any,
    host: str,
    tenant: str,
    site: str,
    job_path: str,
    *,
    now: datetime | None = None,
) -> PastedDetails | None:
    """`GET https://<host>/wday/cxs/<tenant>/<site>/<job_path>` for a pasted
    link; `job_path` is `JobRef.job_id` ("job/<...>")."""
    if not isinstance(data, dict):
        return None
    info = data.get("jobPostingInfo")
    path = _safe_workday_path("/" + job_path.lstrip("/")) if isinstance(job_path, str) else None
    if not isinstance(info, dict) or path is None:
        return None
    title = clean_text(info.get("title"), MAX_TITLE)
    if not title:
        return None
    org = data.get("hiringOrganization")
    company = clean_text(org.get("name"), MAX_COMPANY) if isinstance(org, dict) else ""
    raw_locations = [info.get("location")]
    if isinstance(info.get("additionalLocations"), list):
        raw_locations += info["additionalLocations"]
    date_posted = _from_iso(info.get("startDate"))
    if date_posted is None:
        date_posted = parse_workday_posted_on(info.get("postedOn"), now or datetime.now(UTC))
    return PastedDetails(
        company=company or company_from_token(tenant),
        title=title,
        locations=_workday_locations(raw_locations),
        date_posted=date_posted,
        source=PostingSource.WORKDAY,
        source_key=workday_source_key(host, tenant, site, path),
    )


# --- pasted pages ------------------------------------------------------------


class _PageScanner(HTMLParser):
    """Collects JSON-LD scripts, og:title, og:site_name and the first <title>.
    Reads text only: nothing is executed, loaded or followed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.og: dict[str, str] = {}
        self.title: str | None = None
        self._in_jsonld = False
        self._in_title = False
        self._svg_depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "script":
            mime = values.get("type", "").split(";", 1)[0].strip().lower()
            self._in_jsonld = mime == "application/ld+json"
            self._buffer = []
        elif tag == "title" and self.title is None and not self._svg_depth:
            self._in_title = True
            self._buffer = []
        elif tag == "meta":
            prop = (values.get("property") or values.get("name") or "").strip().lower()
            if prop in ("og:title", "og:site_name") and prop not in self.og:
                self.og[prop] = values.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buffer))
            self._in_jsonld = False
        elif tag == "title" and self._in_title:
            self.title = "".join(self._buffer)
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld or self._in_title:
            self._buffer.append(data)


def _is_job_posting(node: dict) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "JobPosting" in kinds


def _find_job_posting(node: Any, depth: int = 0) -> dict | None:
    """The first JobPosting in a JSON-LD value: an object, a list, or @graph."""
    if depth > _JSONLD_MAX_DEPTH:
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_job_posting(item, depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(node, dict):
        return None
    if _is_job_posting(node):
        return node
    return _find_job_posting(node.get("@graph"), depth + 1)


def _ld_text(value: Any, limit: int) -> str:
    # JSON-LD values are often HTML-escaped ("R&amp;D").
    return clean_text(html.unescape(value), limit) if isinstance(value, str) else ""


def _ld_name(value: Any, limit: int) -> str:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("name")
    return _ld_text(value, limit)


def _ld_locations(posting: dict) -> list[str]:
    places = posting.get("jobLocation")
    places = places if isinstance(places, list) else [places]
    raw: list[str] = []
    for place in places[: MAX_LOCATIONS * 2]:
        if isinstance(place, str):
            raw.append(_ld_text(place, MAX_LOCATION))
            continue
        if not isinstance(place, dict):
            continue
        address = place.get("address")
        if isinstance(address, str):
            raw.append(_ld_text(address, MAX_LOCATION))
        elif isinstance(address, dict):
            parts = [
                _ld_name(address.get(field), MAX_LOCATION)
                for field in ("addressLocality", "addressRegion", "addressCountry")
            ]
            raw.append(", ".join(part for part in parts if part))
    location_type = posting.get("jobLocationType")
    types = location_type if isinstance(location_type, list) else [location_type]
    if any(isinstance(t, str) and t.strip().upper() == "TELECOMMUTE" for t in types):
        raw.append("Remote")
    return _locations(raw)


def _load_jsonld(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def parse_html_posting(html_text: str, url: str) -> PastedDetails:
    """Details of a pasted page that is not on a known board (spec §2c): the
    first JSON-LD JobPosting; else og:title, else <title>. Fields the page
    does not give come back empty for the user to fill in."""
    scanner = _PageScanner()
    try:
        scanner.feed(html_text if isinstance(html_text, str) else "")
        scanner.close()
    except (AssertionError, ValueError):  # malformed markup; keep what was read
        pass

    posting = None
    for script in scanner.jsonld:
        posting = _find_job_posting(_load_jsonld(script))
        if posting is not None:
            break

    title = company = ""
    locations: list[str] = []
    date_posted = None
    if posting is not None:
        title = _ld_text(posting.get("title"), MAX_TITLE)
        company = _ld_name(posting.get("hiringOrganization"), MAX_COMPANY)
        locations = _ld_locations(posting)
        date_posted = _from_iso(posting.get("datePosted"))
    title = (
        title
        or clean_text(scanner.og.get("og:title"), MAX_TITLE)
        or clean_text(scanner.title, MAX_TITLE)
    )
    company = (
        company
        or clean_text(scanner.og.get("og:site_name"), MAX_COMPANY)
        or company_from_token(_host_label(url))
    )
    return PastedDetails(
        company=company,
        title=title,
        locations=locations,
        date_posted=date_posted,
        source=PostingSource.PASTED,
        source_key=normalize_url(url) or clean_text(url, MAX_SOURCE_KEY),
    )
