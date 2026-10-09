"""The Discover Inbox's local match score (Phase 5 spec §3-§4).

`Ranker.score` is pure: it reads what a posting carries and the ranking
preferences and returns a 0-100 score with up to six short reasons. The
rest of the module stores those scores: `rescore` re-scores every `new` and
`saved` posting in one statement (after a preferences change, and once a
day for freshness), and `apply_score` sets them on one ORM row (ingest and
paste-a-link).

Preference values are user input: keywords are escaped before they reach a
regular expression.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import Text, bindparam, cast, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.posting import Posting, PostingState

MAX_SCORE = 100
# Every posting scores this when no preference is set, so the Inbox falls
# back to newest first (spec §4).
NEUTRAL_SCORE = 50
MAX_REASONS = 6
MAX_REASON_LENGTH = 120

ROLE_FIRST = 40
ROLE_EXTRA = 5
ROLE_MAX = 50
SKILL_EACH = 5
SKILL_MAX = 15
LOCATION_POINTS = 15
COMPANY_POINTS = 15
# (posted at most this long ago, points), checked in order.
FRESHNESS = ((timedelta(days=3), 10), (timedelta(days=7), 6), (timedelta(days=14), 3))

# Postings re-scored together have the same states (spec §4).
RESCORED_STATES = (PostingState.NEW, PostingState.SAVED)

_REMOTE = "remote"


@dataclass(frozen=True)
class RankingPrefs:
    role_keywords: tuple[str, ...] = ()
    skill_keywords: tuple[str, ...] = ()
    preferred_locations: tuple[str, ...] = ()
    preferred_companies: tuple[str, ...] = ()
    avoid_companies: tuple[str, ...] = ()
    dealbreaker_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for f in fields(self):
            object.__setattr__(self, f.name, tuple(_clean(getattr(self, f.name))))

    @property
    def empty(self) -> bool:
        return not any(getattr(self, f.name) for f in fields(self))


# The settings columns behind each preference, in `RankingPrefs` order.
PREF_COLUMNS = {
    "role_keywords": "ranking_role_keywords",
    "skill_keywords": "ranking_skill_keywords",
    "preferred_locations": "ranking_preferred_locations",
    "preferred_companies": "ranking_preferred_companies",
    "avoid_companies": "ranking_avoid_companies",
    "dealbreaker_keywords": "ranking_dealbreaker_keywords",
}


def prefs_from_settings(s: AppSettings) -> RankingPrefs:
    return RankingPrefs(**{name: getattr(s, column) for name, column in PREF_COLUMNS.items()})


class PostingFacts(Protocol):
    """What scoring reads: a `Posting` or a row selected with these columns."""

    company: str
    title: str
    locations: Sequence[str]
    category: str | None
    date_posted: datetime | None
    first_seen_at: datetime
    watch_company_id: int | None


@dataclass(frozen=True)
class LocalScore:
    score: int
    reasons: list[str]


def _clean(values: Iterable[str]) -> list[str]:
    """Collapse whitespace, drop blanks and case-insensitive duplicates."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.split())
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _word(keyword: str) -> re.Pattern[str]:
    """`keyword` as a whole word, ignoring case. Like the Inbox filters, an
    edge that is not a word character ("c++", ".net") needs only a non-word
    character or the end of the text next to it."""
    return re.compile(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", re.IGNORECASE)


def _quoted(words: Iterable[str]) -> str:
    return ", ".join(f"'{w}'" for w in words)


def _days_ago(age: timedelta) -> str:
    days = max(0, age.days)
    if days == 0:
        return "posted today"
    return "posted 1 day ago" if days == 1 else f"posted {days} days ago"


class Ranker:
    """Preferences compiled once, for scoring many postings."""

    def __init__(self, prefs: RankingPrefs) -> None:
        self.prefs = prefs
        self._roles = [(k, _word(k)) for k in prefs.role_keywords]
        self._skills = [(k, _word(k)) for k in prefs.skill_keywords]
        self._dealbreakers = [(k, _word(k)) for k in prefs.dealbreaker_keywords]
        self._preferred = [_word(k) for k in prefs.preferred_companies]
        self._avoided = [_word(k) for k in prefs.avoid_companies]
        self._locations = [(k, k.casefold()) for k in prefs.preferred_locations]

    def score(self, p: PostingFacts, now: datetime) -> LocalScore:
        if self.prefs.empty:
            return LocalScore(NEUTRAL_SCORE, [])

        title = p.title or ""
        company = p.company or ""
        dealbreakers = [k for k, rx in self._dealbreakers if rx.search(title)]
        avoided = any(rx.search(company) for rx in self._avoided)
        if dealbreakers or avoided:
            reasons = []
            if dealbreakers:
                reasons.append(f"Dealbreaker: {_quoted(dealbreakers)}")
            if avoided:
                reasons.append("Avoided company")
            return LocalScore(0, _capped(reasons))

        points = 0
        reasons: list[str] = []

        roles = [k for k, rx in self._roles if rx.search(title)]
        if roles:
            points += min(ROLE_MAX, ROLE_FIRST + ROLE_EXTRA * (len(roles) - 1))
            reasons.append(f"Title matches {_quoted(roles)}")

        skill_text = f"{title}\n{p.category or ''}"
        skills = [k for k, rx in self._skills if rx.search(skill_text)]
        if skills:
            points += min(SKILL_MAX, SKILL_EACH * len(skills))
            reasons.append(f"Skills: {', '.join(skills)}")

        location = self._location(p, title)
        if location is not None:
            points += LOCATION_POINTS
            reasons.append(location)

        if any(rx.search(company) for rx in self._preferred):
            points += COMPANY_POINTS
            reasons.append("Preferred company")
        elif p.watch_company_id is not None:
            points += COMPANY_POINTS
            reasons.append("Watchlist company")

        posted = p.date_posted or p.first_seen_at
        if posted is not None:
            age = now - posted
            for limit, fresh in FRESHNESS:
                if age <= limit:
                    points += fresh
                    reasons.append(_days_ago(age))
                    break

        return LocalScore(min(MAX_SCORE, points), _capped(reasons))

    def _location(self, p: PostingFacts, title: str) -> str | None:
        """The first preferred location found in the posting's locations
        (case-insensitive substring). "Remote" also matches the title."""
        locations = [loc.casefold() for loc in p.locations or ()]
        for spelling, wanted in self._locations:
            if any(wanted in loc for loc in locations):
                return spelling
            if wanted == _REMOTE and _REMOTE in title.casefold():
                return spelling
        return None


def _capped(reasons: list[str]) -> list[str]:
    return [r[:MAX_REASON_LENGTH] for r in reasons[:MAX_REASONS]]


def score_posting(p: PostingFacts, prefs: RankingPrefs, now: datetime) -> LocalScore:
    return Ranker(prefs).score(p, now)


# --- storage -------------------------------------------------------------------


def apply_score(posting: Posting, ranker: Ranker, now: datetime) -> None:
    """Set one ORM row's local score (the caller commits)."""
    result = ranker.score(posting, now)
    posting.local_score = result.score
    posting.local_reasons = result.reasons


_SCORED_COLUMNS = (
    Posting.id,
    Posting.company,
    Posting.title,
    Posting.locations,
    Posting.category,
    Posting.date_posted,
    Posting.first_seen_at,
    Posting.watch_company_id,
    Posting.local_score,
    Posting.local_reasons,
)


def rescore(db: Session, prefs: RankingPrefs, now: datetime) -> int:
    """Recompute the local score of every `new` and `saved` posting in one
    UPDATE (no commit: the caller's transaction covers it). Rows whose score
    and reasons are unchanged are left alone. Returns the rows updated."""
    ranker = Ranker(prefs)
    ids: list[int] = []
    scores: list[int] = []
    reasons: list[str] = []  # JSON text: a jsonb[] parameter would nest the lists
    rows = db.execute(select(*_SCORED_COLUMNS).where(Posting.state.in_(RESCORED_STATES)))
    for row in rows:
        result = ranker.score(row, now)
        if result.score == row.local_score and result.reasons == row.local_reasons:
            continue
        ids.append(row.id)
        scores.append(result.score)
        reasons.append(json.dumps(result.reasons))
    if not ids:
        return 0
    values = (
        select(
            func.unnest(bindparam("ids", ids, type_=ARRAY(Posting.id.type))).label("id"),
            func.unnest(bindparam("scores", scores, type_=ARRAY(Posting.local_score.type))).label("score"),
            cast(func.unnest(bindparam("reasons", reasons, type_=ARRAY(Text))), JSONB).label("reasons"),
        )
        .subquery("v")
    )
    db.execute(
        update(Posting)
        .where(Posting.id == values.c.id)
        .values(local_score=values.c.score, local_reasons=values.c.reasons)
        .execution_options(synchronize_session=False)
    )
    # Postings already loaded in this session must not show their old score.
    for obj in list(db.identity_map.values()):
        if isinstance(obj, Posting):
            db.expire(obj, ["local_score", "local_reasons"])
    return len(ids)
