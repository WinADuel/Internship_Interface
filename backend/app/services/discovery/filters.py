"""Query-time discovery filters, the Inbox/Saved/Dismissed listings and the
live match count (Phase 2 spec §4 and §7, plan Task 6).

Filters are applied when postings are listed, never when they are stored, so
changing a filter re-sorts existing postings at once. Every filter list is
"any" when empty. Filter values are user input: keywords are escaped before
they reach a regular expression and locations before they reach ILIKE.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, fields
from typing import Literal

from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select, true
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.posting import Posting, PostingSource, PostingState
from app.services.discovery.ingest import BOARD_SOURCES

LIST_SOURCES = frozenset({PostingSource.SIMPLIFY, PostingSource.VANSHB03, PostingSource.LIST})
# Values the community lists use for "no sponsorship" (spec §4).
NO_SPONSORSHIP = ("Does Not Offer Sponsorship", "U.S. Citizenship is Required")
# The Dismissed tab shows the most recent 200 (spec §7).
DISMISSED_CAP = 200

View = Literal["inbox", "saved", "dismissed"]

# A four-digit year, on both the Python and the Postgres side.
_YEAR = "[0-9]{4}"
_YEAR_RE = re.compile(_YEAR)
# Postgres word characters are alphanumerics and underscore. \m / \M only
# match next to one, so keyword edges that are not word characters ("c++",
# ".net", "c#") use an explicit "start/end or a non-word character" boundary.
_LEFT_EDGE = r"(^|[^[:alnum:]_])"
_RIGHT_EDGE = r"($|[^[:alnum:]_])"


@dataclass(frozen=True)
class DiscoveryFilters:
    terms: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    watchlist_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    hide_no_sponsorship: bool = False

    def __post_init__(self) -> None:
        # Accept any iterable (settings columns are lists); store tuples so the
        # value stays immutable and hashable.
        for f in fields(self):
            if f.name != "hide_no_sponsorship":
                object.__setattr__(self, f.name, tuple(getattr(self, f.name)))


def filters_from_settings(s: AppSettings) -> DiscoveryFilters:
    return DiscoveryFilters(
        terms=s.discovery_terms,
        categories=s.discovery_categories,
        include_keywords=s.discovery_include_keywords,
        watchlist_keywords=s.discovery_watchlist_keywords,
        exclude_keywords=s.discovery_exclude_keywords,
        locations=s.discovery_locations,
        hide_no_sponsorship=s.discovery_hide_no_sponsorship,
    )


def _clean(values: Iterable[str]) -> list[str]:
    """Strip, drop blanks and case-insensitive duplicates (first spelling wins)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.split())
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def _is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _escape_regex(text: str) -> str:
    """Escape for a Postgres ARE: a backslash before any character that is not
    a word character or a space makes it literal. Word characters are never
    escaped (a backslash before one would start an escape like \\m)."""
    return "".join(c if _is_word_char(c) or c == " " else "\\" + c for c in text)


def _word_pattern(keyword: str) -> str:
    left = r"\m" if _is_word_char(keyword[0]) else _LEFT_EDGE
    right = r"\M" if _is_word_char(keyword[-1]) else _RIGHT_EDGE
    return left + _escape_regex(keyword) + right


def keyword_regex(keywords: Iterable[str]) -> str | None:
    """One case-insensitive (`~*`) pattern matching any keyword as a whole
    word, or None when there are no keywords."""
    words = _clean(keywords)
    if not words:
        return None
    return "(" + "|".join(_word_pattern(w) for w in words) + ")"


def _title_has_any(keywords: Iterable[str]) -> ColumnElement[bool] | None:
    pattern = keyword_regex(keywords)
    return None if pattern is None else Posting.title.bool_op("~*")(pattern)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _term_rule(terms: Iterable[str]) -> ColumnElement[bool] | None:
    """One of the posting's terms is one of `terms`, ignoring case. A posting
    term with no year ("Summer", as vanshb03 writes it) also matches a filter
    term with a year and the same season word ("Summer 2027")."""
    wanted = _clean(terms)
    if not wanted:
        return None
    exact = [t.lower() for t in wanted]
    seasons = sorted(
        {" ".join(_YEAR_RE.sub(" ", t).split()).lower() for t in wanted if _YEAR_RE.search(t)} - {""}
    )
    term = func.unnest(Posting.terms).column_valued("term")
    normalized = func.lower(func.btrim(term))
    match = normalized.in_(exact)
    if seasons:
        match = or_(match, and_(term.bool_op("!~")(_YEAR), normalized.in_(seasons)))
    return exists().where(match)


def _location_rule(locations: Iterable[str]) -> ColumnElement[bool] | None:
    wanted = _clean(locations)
    if not wanted:
        return None
    loc = func.unnest(Posting.locations).column_valued("loc")
    return exists().where(or_(*(loc.ilike(f"%{_escape_like(w)}%", escape="\\") for w in wanted)))


def inbox_clause(f: DiscoveryFilters) -> ColumnElement[bool]:
    """Whether a posting is in the Inbox (spec §4): `new`, not closed, not
    pasted, and passing every filter. List-only rules (term, category,
    sponsorship) and the board-only watchlist-keyword rule are skipped for
    the other kind of source."""
    list_rules: list[ColumnElement[bool]] = []
    board_rules: list[ColumnElement[bool]] = []
    common: list[ColumnElement[bool]] = [
        Posting.state == PostingState.NEW,
        Posting.closed.is_(false()),
        Posting.source != PostingSource.PASTED,
    ]

    if (rule := _term_rule(f.terms)) is not None:
        list_rules.append(rule)
    categories = [c.lower() for c in _clean(f.categories)]
    if categories:
        # A list that does not categorise its rows (vanshb03) is not filtered
        # by category; a categorised row must be in the chosen ones.
        list_rules.append(or_(Posting.category.is_(None), func.lower(Posting.category).in_(categories)))
    if f.hide_no_sponsorship:
        hidden = [v.lower() for v in NO_SPONSORSHIP]
        list_rules.append(or_(Posting.sponsorship.is_(None), func.lower(Posting.sponsorship).not_in(hidden)))
    if (rule := _title_has_any(f.watchlist_keywords)) is not None:
        board_rules.append(rule)
    if (rule := _title_has_any(f.include_keywords)) is not None:
        common.append(rule)
    if (rule := _title_has_any(f.exclude_keywords)) is not None:
        common.append(~rule)
    if (rule := _location_rule(f.locations)) is not None:
        common.append(rule)

    if list_rules:
        common.append(or_(Posting.source.not_in(LIST_SOURCES), and_(*list_rules)))
    if board_rules:
        common.append(or_(Posting.source.not_in(BOARD_SOURCES), and_(*board_rules)))
    return and_(true(), *common)


def _check_paging(limit: int, offset: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")


def list_postings(
    db: Session,
    view: View,
    filters: DiscoveryFilters,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Posting], int]:
    """One page of a Discover tab and the tab's total. The Inbox applies
    `filters`; Saved and Dismissed show every posting in that state (closed
    ones included) and ignore them. Dismissed is capped at the most recent
    `DISMISSED_CAP`, and its total is capped too."""
    _check_paging(limit, offset)
    if view == "inbox":
        where = inbox_clause(filters)
        order = (
            Posting.claude_score.desc().nulls_last(),
            func.coalesce(Posting.date_posted, Posting.first_seen_at).desc(),
            Posting.id.desc(),
        )
    elif view in ("saved", "dismissed"):
        state = PostingState.SAVED if view == "saved" else PostingState.DISMISSED
        where = Posting.state == state
        order = (Posting.state_changed_at.desc(), Posting.id.desc())
    else:
        raise ValueError(f"unknown view: {view!r}")

    if view == "dismissed":
        capped = select(Posting.id).where(where).limit(DISMISSED_CAP).subquery()
        total = db.scalar(select(func.count()).select_from(capped)) or 0
        if offset >= DISMISSED_CAP:
            return [], total
        limit = min(limit, DISMISSED_CAP - offset)
    else:
        total = db.scalar(select(func.count()).select_from(Posting).where(where)) or 0

    items = list(db.scalars(select(Posting).where(where).order_by(*order).limit(limit).offset(offset)))
    return items, total


def match_count(db: Session, filters: DiscoveryFilters) -> int:
    """How many postings the Inbox would show with `filters` (which need not
    be saved): powers the live count in Settings → Job discovery."""
    return db.scalar(select(func.count()).select_from(Posting).where(inbox_clause(filters))) or 0
