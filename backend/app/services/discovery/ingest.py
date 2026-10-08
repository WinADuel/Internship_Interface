"""Ingest one source's postings into `postings`, and housekeeping
(Phase 2 spec §3, plan Task 5).

`ingest` upserts by `(source, source_key)`, skips new postings that another
row already covers (same `url_key` anywhere, or the same company and title
from a different source in the last 14 days), and, for a complete result,
closes the source's postings that are no longer listed. A failed source
changes nothing. Existing rows never have their `state`, `application_id`
or `claude_*` fields touched here.

Work is done in bulk: a handful of targeted queries per call, `add_all` for
inserts, one UPDATE for closing, and one commit.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.posting import Posting, PostingSource, PostingState
from app.services.discovery.parsers import PostingIn
from app.services.discovery.sources import SourceResult
from app.services.discovery.urls import normalize_url

BOARD_SOURCES = frozenset(
    {
        PostingSource.GREENHOUSE,
        PostingSource.LEVER,
        PostingSource.ASHBY,
        PostingSource.WORKDAY,
    }
)
# A new posting with the same company and title as another source's posting
# first seen within this window is the same role (spec §3).
DUPLICATE_WINDOW = timedelta(days=14)
# New or dismissed postings older than this are deleted by housekeeping.
HOUSEKEEPING_AGE = timedelta(days=90)

# Bound on bind parameters per IN (...) list.
_IN_CHUNK = 5000

T = TypeVar("T")


@dataclass(frozen=True)
class IngestStats:
    added: int = 0
    updated: int = 0
    closed: int = 0
    skipped_duplicates: int = 0


def _chunks(items: Sequence[T]) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), _IN_CHUNK):
        yield items[start : start + _IN_CHUNK]


def _pair(company: str, title: str) -> tuple[str, str]:
    # Python's lower() and Postgres lower() agree for the text these sources carry.
    return company.lower(), title.lower()


def _load_existing(
    db: Session, keys: dict[PostingSource, list[str]]
) -> dict[tuple[PostingSource, str], Posting]:
    existing: dict[tuple[PostingSource, str], Posting] = {}
    for source, source_keys in keys.items():
        for chunk in _chunks(source_keys):
            rows = db.scalars(
                select(Posting).where(
                    Posting.source == source, Posting.source_key.in_(chunk)
                )
            )
            for row in rows:
                existing[(row.source, row.source_key)] = row
    return existing


def _load_url_keys(db: Session, url_keys: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for chunk in _chunks(sorted(set(url_keys))):
        found.update(
            db.scalars(
                select(Posting.url_key).where(Posting.url_key.in_(chunk)).distinct()
            )
        )
    return found


def _load_recent_pairs(
    db: Session, companies: Iterable[str], since: datetime
) -> dict[tuple[str, str], set[PostingSource]]:
    """(lower company, lower title) → sources of postings first seen since `since`,
    for the given lowercased companies."""
    pairs: dict[tuple[str, str], set[PostingSource]] = {}
    lower_company = func.lower(Posting.company)
    for chunk in _chunks(sorted(set(companies))):
        rows = db.execute(
            select(lower_company, func.lower(Posting.title), Posting.source).where(
                lower_company.in_(chunk), Posting.first_seen_at >= since
            )
        )
        for company, title, source in rows:
            pairs.setdefault((company, title), set()).add(source)
    return pairs


def _apply_update(
    row: Posting,
    posting: PostingIn,
    url_key: str,
    now: datetime,
    watch_company_id: int | None,
) -> bool:
    """Refresh an existing row from its source. Returns True if this closed it."""
    was_closed = row.closed
    row.company = posting.company
    row.title = posting.title
    row.locations = list(posting.locations)
    row.url = posting.url
    row.url_key = url_key
    row.terms = list(posting.terms)
    row.category = posting.category
    row.sponsorship = posting.sponsorship
    row.last_seen_at = now
    row.closed = not posting.active
    if watch_company_id is not None:
        row.watch_company_id = watch_company_id
    return row.closed and not was_closed


def _close_missing(
    db: Session,
    result: SourceResult,
    source: PostingSource,
    present: set[str],
    watch_company_id: int | None,
) -> int:
    """Close the source's open postings that a complete result no longer lists."""
    if source in BOARD_SOURCES and watch_company_id is None:
        # Board keys are not scoped per company, so without the company this
        # would close every other watched board's postings.
        return 0
    conditions = [Posting.source == source, Posting.closed.is_(False)]
    if result.key_prefix is not None:
        conditions.append(
            Posting.source_key.startswith(f"{result.key_prefix}:", autoescape=True)
        )
    if watch_company_id is not None:
        conditions.append(Posting.watch_company_id == watch_company_id)
    rows = db.execute(select(Posting.id, Posting.source_key).where(*conditions))
    ids = [row_id for row_id, key in rows if key not in present]
    for chunk in _chunks(ids):
        db.execute(update(Posting).where(Posting.id.in_(chunk)).values(closed=True))
    return len(ids)


def ingest(
    db: Session,
    result: SourceResult,
    now: datetime,
    watch_company_id: int | None = None,
) -> IngestStats:
    """Upsert one source's result. See the module docstring for the rules."""
    if result.error is not None:
        return IngestStats()

    source = result.source
    if source is None and result.postings:
        source = result.postings[0].source

    # 1. Rows worth looking at, first occurrence of each (source, key) and url.
    skipped = 0
    rows: list[tuple[PostingIn, str]] = []
    seen_keys: set[tuple[PostingSource, str]] = set()
    present: set[str] = set()  # this source's keys listed in the result
    for posting in result.postings:
        identity = (posting.source, posting.source_key)
        if identity in seen_keys:
            skipped += 1
            continue
        seen_keys.add(identity)
        if posting.source == source:
            present.add(posting.source_key)
        url_key = normalize_url(posting.url)
        if url_key is None:
            continue
        rows.append((posting, url_key))

    keys_by_source: dict[PostingSource, list[str]] = {}
    for posting, _ in rows:
        keys_by_source.setdefault(posting.source, []).append(posting.source_key)
    existing = _load_existing(db, keys_by_source)

    # 2. Update rows the source already had.
    updated = 0
    closed = 0
    new_rows: list[tuple[PostingIn, str]] = []
    for posting, url_key in rows:
        row = existing.get((posting.source, posting.source_key))
        if row is None:
            if posting.active:
                new_rows.append((posting, url_key))
            continue
        updated += 1
        if _apply_update(row, posting, url_key, now, watch_company_id):
            closed += 1

    # 3. Insert new rows that nothing already covers.
    since = now - DUPLICATE_WINDOW
    known_urls = _load_url_keys(db, (url_key for _, url_key in new_rows))
    recent = _load_recent_pairs(db, (p.company.lower() for p, _ in new_rows), since)
    # Updates above may have moved existing rows onto new urls or titles.
    for row in existing.values():
        known_urls.add(row.url_key)
        if row.first_seen_at >= since:
            recent.setdefault(_pair(row.company, row.title), set()).add(row.source)

    inserts: list[Posting] = []
    for posting, url_key in new_rows:
        pair = _pair(posting.company, posting.title)
        other_sources = recent.get(pair, set()) - {posting.source}
        if url_key in known_urls or other_sources:
            skipped += 1
            continue
        known_urls.add(url_key)
        recent.setdefault(pair, set()).add(posting.source)
        inserts.append(
            Posting(
                source=posting.source,
                source_key=posting.source_key,
                company=posting.company,
                title=posting.title,
                locations=list(posting.locations),
                url=posting.url,
                url_key=url_key,
                terms=list(posting.terms),
                category=posting.category,
                sponsorship=posting.sponsorship,
                date_posted=posting.date_posted,
                first_seen_at=now,
                last_seen_at=now,
                closed=False,
                state=PostingState.NEW,
                state_changed_at=now,
                watch_company_id=watch_company_id,
            )
        )

    # 4. Close what a complete listing no longer shows.
    if result.complete and source is not None:
        db.flush()
        closed += _close_missing(db, result, source, present, watch_company_id)

    db.add_all(inserts)
    db.commit()
    return IngestStats(
        added=len(inserts), updated=updated, closed=closed, skipped_duplicates=skipped
    )


def housekeep(db: Session, now: datetime) -> int:
    """Delete new or dismissed postings that are closed or older than 90 days.
    Saved and applied postings are never deleted. Returns the number deleted."""
    deleted = db.execute(
        delete(Posting).where(
            Posting.state.in_([PostingState.NEW, PostingState.DISMISSED]),
            or_(
                Posting.closed.is_(True),
                Posting.first_seen_at < now - HOUSEKEEPING_AGE,
            ),
        )
    )
    db.commit()
    return deleted.rowcount
