"""URL tools for job discovery (Phase 2 spec §2b, §2c, §3, §9).

Pure functions: no network. Everything here treats its input as untrusted.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.watch_company import WatchAts

MAX_URL_LENGTH = 2000

BOARD_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
WORKDAY_HOST_RE = re.compile(r"^[a-z0-9-]+\.wd\d{1,3}\.myworkdayjobs\.com$")
_GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})
_LEVER_HOST = "jobs.lever.co"
_ASHBY_HOST = "jobs.ashbyhq.com"
_GREENHOUSE_JOB_ID_RE = re.compile(r"^\d{1,20}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
# Workday prefixes the site with a locale on many links: en-US, fr-CA, en-us, en.
_WORKDAY_LOCALE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$", re.IGNORECASE)
# Workday job slugs seen in real list data use only these characters.
_WORKDAY_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")

# Query parameters that only track where a click came from. Dropping them
# lets the same job from two lists share one url_key.
_TRACKING_PARAMS = frozenset({"gh_src", "source", "ref", "lever-source", "lever-origin"})
# gh_jid is Greenhouse's job id. On Greenhouse's own hosts the id is also in
# the path, so it is redundant there; on a company's own careers page
# (careers.withwaymo.com/jobs?gh_jid=...) it is the only identifier and must stay.
_GREENHOUSE_ID_PARAM = "gh_jid"

_DEFAULT_PORTS = {"http": 80, "https": 443}

# Companies with their own careers sites, which can't be watched (spec §2b).
# Keys are host suffixes; a host matches when it equals a key or ends with
# "." + key.
KNOWN_CUSTOM_SITES: dict[str, str] = {
    "google.com": "Google",
    "careers.google.com": "Google",
    "microsoft.com": "Microsoft",
    "apple.com": "Apple",
    "metacareers.com": "Meta",
    "meta.com": "Meta",
    "amazon.jobs": "Amazon",
    "amazon.com": "Amazon",
}


@dataclass(frozen=True)
class BoardRef:
    ats: WatchAts
    # Greenhouse/Lever/Ashby: the board token. Workday: "<host>/<tenant>/<site>".
    token: str


@dataclass(frozen=True)
class JobRef:
    ats: WatchAts
    token: str
    # Greenhouse: numeric id. Lever/Ashby: lowercase UUID. Workday: the path
    # after the site, starting with "job/".
    job_id: str


def _has_unsafe_chars(value: str) -> bool:
    return any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in value)


def _split_http(url: object):
    """urlsplit `url` if it is an absolute http(s) URL with a host, else None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or _has_unsafe_chars(url):
        return None
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 — raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme.lower() not in _DEFAULT_PORTS or not parts.hostname:
        return None
    return parts


def safe_http_url(url: str) -> str | None:
    """The stripped URL if it is an absolute http(s) URL with a host, at most
    2000 characters and free of whitespace/control characters; else None."""
    if not isinstance(url, str):
        return None
    stripped = url.strip()
    if len(stripped) > MAX_URL_LENGTH or _split_http(stripped) is None:
        return None
    return stripped


def _is_greenhouse_host(host: str) -> bool:
    return host == "greenhouse.io" or host.endswith(".greenhouse.io")


def normalize_url(url: str) -> str | None:
    """The de-duplication key for a posting URL (`postings.url_key`): None
    unless http(s) with a host. Lowercases scheme and host, drops userinfo,
    default ports, the fragment, a trailing "/" and tracking query params,
    and sorts the remaining params."""
    parts = _split_http(url)
    if parts is None:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()  # urlsplit already lowercases; be explicit
    netloc = f"[{host}]" if ":" in host else host
    port = parts.port
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/")
    drop_gh_jid = _is_greenhouse_host(host)
    params = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = name.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_PARAMS:
            continue
        if drop_gh_jid and lowered == _GREENHOUSE_ID_PARAM:
            continue
        params.append((name, value))
    query = urlencode(sorted(params))
    return urlunsplit((scheme, netloc, path, query, ""))


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def _token(value: str | None) -> str | None:
    return value if value is not None and BOARD_TOKEN_RE.match(value) else None


def _query_value(query: str, name: str) -> str | None:
    values = parse_qs(query).get(name)
    return values[0] if values else None


def _workday_parts(host: str, segs: list[str]) -> tuple[str, list[str]] | None:
    """(token, rest-after-site) for a Workday URL, or None."""
    if not WORKDAY_HOST_RE.match(host):
        return None
    tenant = host.split(".", 1)[0]
    if not BOARD_TOKEN_RE.match(tenant) or not segs:
        return None
    # A leading locale ("en-US") is skipped only when a site follows it and
    # that next segment is not itself the start of a job path.
    if len(segs) >= 2 and _WORKDAY_LOCALE_RE.match(segs[0]) and segs[1] not in ("job", "details"):
        segs = segs[1:]
    elif len(segs) == 1 and _WORKDAY_LOCALE_RE.match(segs[0]):
        return None  # a bare locale ("/en-US") names no site
    site = _token(segs[0])
    if site is None:
        return None
    return f"{host}/{tenant}/{site}", segs[1:]


def parse_board_url(url: str) -> BoardRef | None:
    """Recognize a Greenhouse, Lever, Ashby or Workday careers URL (spec §2b).
    Job URLs on those boards also resolve to their board."""
    parts = _split_http(url)
    if parts is None:
        return None
    host = parts.hostname.lower()
    segs = _segments(parts.path)
    if host in _GREENHOUSE_HOSTS:
        if segs[:2] == ["embed", "job_board"]:
            token = _token(_query_value(parts.query, "for"))
        elif segs and segs[0] != "embed":
            token = _token(segs[0])
        else:
            token = None
        return BoardRef(WatchAts.GREENHOUSE, token) if token else None
    if host == _LEVER_HOST:
        token = _token(segs[0]) if segs else None
        return BoardRef(WatchAts.LEVER, token) if token else None
    if host == _ASHBY_HOST:
        token = _token(segs[0]) if segs else None
        return BoardRef(WatchAts.ASHBY, token) if token else None
    workday = _workday_parts(host, segs)
    if workday is not None:
        return BoardRef(WatchAts.WORKDAY, workday[0])
    return None


def parse_job_url(url: str) -> JobRef | None:
    """Recognize a single-job URL on Greenhouse, Lever, Ashby or Workday, so a
    pasted link can be read from the board's API (spec §2c)."""
    parts = _split_http(url)
    if parts is None:
        return None
    host = parts.hostname.lower()
    segs = _segments(parts.path)
    if host in _GREENHOUSE_HOSTS:
        if segs[:2] == ["embed", "job_app"]:
            token = _token(_query_value(parts.query, "for"))
            job_id = _query_value(parts.query, "token")
        elif len(segs) == 3 and segs[1] == "jobs" and segs[0] != "embed":
            token, job_id = _token(segs[0]), segs[2]
        else:
            return None
        if token and job_id and _GREENHOUSE_JOB_ID_RE.match(job_id):
            return JobRef(WatchAts.GREENHOUSE, token, job_id)
        return None
    if host in (_LEVER_HOST, _ASHBY_HOST):
        ats, suffix = (
            (WatchAts.LEVER, "apply") if host == _LEVER_HOST else (WatchAts.ASHBY, "application")
        )
        if len(segs) == 3 and segs[2] == suffix:
            segs = segs[:2]
        if len(segs) != 2:
            return None
        token, job_id = _token(segs[0]), segs[1]
        if token and _UUID_RE.match(job_id):
            return JobRef(ats, token, job_id.lower())
        return None
    workday = _workday_parts(host, segs)
    if workday is not None:
        token, rest = workday
        # job/<slug> or job/<location>/<slug>
        if (
            rest[:1] == ["job"]
            and 2 <= len(rest) <= 3
            and all(_WORKDAY_SLUG_RE.match(s) for s in rest[1:])
        ):
            return JobRef(WatchAts.WORKDAY, token, "/".join(rest))
    return None


def known_custom_site(url: str) -> str | None:
    """The company name when `url` is on a known custom careers site."""
    parts = _split_http(url)
    if parts is None:
        return None
    host = parts.hostname.lower().rstrip(".")
    for suffix, company in KNOWN_CUSTOM_SITES.items():
        if host == suffix or host.endswith("." + suffix):
            return company
    return None
