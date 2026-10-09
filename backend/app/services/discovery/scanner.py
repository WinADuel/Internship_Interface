"""One scan over every source (Phase 2 spec §5, plan Task 7).

`run_scan` downloads each community list (conditional GET), reads each
watched board in turn, ingests what came back, runs housekeeping and records
the outcome in `app_settings`. One broken source never stops the others: a
fetcher's own error result and any unexpected exception are recorded for
that source, and the scan moves on.

Scans are single-flight under a session-level Postgres advisory lock, so the
`job-scan` service and Scan now can never run at the same time.

The lock lives on a dedicated connection, not on the scan's `Session`. A
Session bound to an Engine hands its connection back to the pool at every
commit (and `ingest` commits once per source), so a lock taken through it
could be left on a pooled connection and an unlock could run on a different
one, which would leak the lock. The dedicated connection is opened from the
same engine in autocommit mode (no transaction left idle for the length of
the scan), takes the lock, and unlocks it in `finally`; if the unlock fails
the connection is invalidated, which ends its database session and so
releases the lock.

Whether a scan is running (`is_scan_running`, for the Discover header) is
read out of `pg_locks` on the caller's session: a check that took the lock
would make a scan starting at that moment skip itself.

Local scores (Phase 5 spec §4): each source's ingest scores its rows with the
preferences as they are when that ingest starts, re-read whenever
`ranking_updated_at` moves, so a change saved during a scan is never undone
by the rest of it. Freshness points age even for postings no source
re-lists, so every `new` and `saved` posting is re-scored once
`last_rescore_at` is `RESCORE_EVERY` old: at the end of a scan, and from the
scan job between scans (`rescore_if_due`).
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.watch_company import WatchCompany
from app.services.discovery.filters import filters_from_settings, match_count
from app.services.discovery.http import DiscoveryHttp
from app.services.discovery.ingest import housekeep, ingest, refresh_unchanged
from app.services.discovery.parsers import clean_text
from app.services.discovery.ranking import Ranker, lock_scores, prefs_from_settings, rescore
from app.services.discovery.sources import (
    company_name,
    fetch_board,
    fetch_list,
    list_name,
)
from app.services.settings_service import SETTINGS_ID, get_settings

logger = logging.getLogger(__name__)

# Fixed key for pg_(try_)advisory_lock: "JOBSCAN" in ASCII, well inside bigint.
SCAN_LOCK_KEY = 0x4A4F_4253_4341_4E
LAST_SCAN_ERROR_MAX = 2000
# Seconds between two watched companies' boards.
BOARD_PAUSE = 1.0

# The full re-score runs when the last one is this old: comfortably inside a
# day, so a scan or job wake-up a little early on the next day still runs it.
RESCORE_EVERY = timedelta(hours=20)

_ERROR_SEPARATOR = "; "
_SOURCE_ERROR_MAX = 500


@dataclass
class ScanReport:
    added: int = 0
    closed: int = 0
    removed: int = 0
    # One line per failed source, "<name>: <reason>".
    errors: list[str] = field(default_factory=list)


# --- the lock ----------------------------------------------------------------


@contextmanager
def _lock_connection(db: Session) -> Iterator[Connection]:
    """A connection of its own from the session's engine, in autocommit mode."""
    conn = db.get_bind().engine.connect()
    try:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        yield conn
    finally:
        conn.close()


def _try_lock(conn: Connection) -> bool:
    return bool(
        conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SCAN_LOCK_KEY}).scalar_one()
    )


def _unlock(conn: Connection) -> None:
    try:
        released = conn.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": SCAN_LOCK_KEY}
        ).scalar_one()
    except Exception:  # noqa: BLE001 - the lock must not outlive this call
        logger.exception("could not release the scan lock")
        released = False
    if not released:
        # Closing the database session is what finally releases the lock.
        conn.invalidate()


# Postgres reports a bigint advisory lock in pg_locks as classid = the key's
# high 32 bits, objid = its low 32 bits, objsubid = 1 (2 is the two-int form).
_LOCK_CLASSID = (SCAN_LOCK_KEY >> 32) & 0xFFFF_FFFF
_LOCK_OBJID = SCAN_LOCK_KEY & 0xFFFF_FFFF

_LOCK_HELD_SQL = text(
    "SELECT EXISTS ("
    " SELECT 1 FROM pg_locks"
    " WHERE locktype = 'advisory'"
    " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    " AND classid = :classid AND objid = :objid AND objsubid = 1"
    " AND granted"
    ")"
)


def is_scan_running(db: Session) -> bool:
    """Whether a scan holds the lock right now. Read-only: it looks the lock
    up in `pg_locks` instead of trying to take it, because taking it even for
    an instant (as `pg_try_advisory_lock` would) makes a real scan starting at
    that moment find the lock busy and skip itself."""
    return bool(db.scalar(_LOCK_HELD_SQL, {"classid": _LOCK_CLASSID, "objid": _LOCK_OBJID}))


# --- local scores ------------------------------------------------------------


def _fresh_settings(db: Session) -> AppSettings:
    """The settings row as committed now, not as this session last saw it."""
    settings = get_settings(db)
    db.refresh(settings)
    return settings


class _Ranking:
    """The ranker for a scan's ingests. `current` takes the postings write
    lock (the ingest that follows runs under it) and then compares
    `ranking_updated_at`, one cheap query, rebuilding the ranker only when
    the preferences have changed since it was built."""

    def __init__(self) -> None:
        self._ranker: Ranker | None = None
        self._as_of: datetime | None = None

    def current(self, db: Session) -> Ranker:
        lock_scores(db)
        as_of = db.scalar(select(AppSettings.ranking_updated_at).where(AppSettings.id == SETTINGS_ID))
        if self._ranker is None or as_of != self._as_of:
            self._ranker = Ranker(prefs_from_settings(_fresh_settings(db)))
            self._as_of = as_of
        return self._ranker


def _rescore_due(last: datetime | None, now: datetime) -> bool:
    return last is None or now - last >= RESCORE_EVERY


def _rescore_if_due(db: Session, now: datetime) -> bool:
    """Re-score every `new` and `saved` posting with the preferences as they
    are now, if the last full re-score is `RESCORE_EVERY` old, and record
    it. Commits; on failure rolls back, records nothing (so the next chance
    tries again) and raises. Returns whether it re-scored."""
    try:
        lock_scores(db)
        settings = _fresh_settings(db)
        if not _rescore_due(settings.last_rescore_at, now):
            db.rollback()  # ends the transaction and with it the lock
            return False
        rescore(db, prefs_from_settings(settings), now)
        settings.last_rescore_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def rescore_if_due(db: Session, now: datetime | None = None) -> bool | None:
    """The scan job's check between scans (one small query when nothing is
    due). Returns None, having done nothing, while a scan runs: the scan
    re-scores at its end if it is due."""
    now = now or datetime.now(UTC)
    last = db.scalar(select(AppSettings.last_rescore_at).where(AppSettings.id == SETTINGS_ID))
    if not _rescore_due(last, now):
        return False
    with _lock_connection(db) as conn:
        if not _try_lock(conn):
            return None
        try:
            return _rescore_if_due(db, now)
        finally:
            _unlock(conn)


# --- the scan ----------------------------------------------------------------


def _unexpected(name: str, exc: BaseException) -> str:
    # The exception's message may quote a response or SQL: only its type is kept.
    return clean_text(f"{name}: unexpected error ({type(exc).__name__})", _SOURCE_ERROR_MAX)


def _summary(errors: list[str]) -> str | None:
    if not errors:
        return None
    joined = _ERROR_SEPARATOR.join(errors)
    if len(joined) > LAST_SCAN_ERROR_MAX:
        joined = joined[: LAST_SCAN_ERROR_MAX - 1].rstrip() + "…"
    return joined


def _scan_lists(
    db: Session,
    http: DiscoveryHttp,
    urls: list[str],
    etags: dict[str, str],
    now: datetime,
    ranking: _Ranking,
    report: ScanReport,
) -> None:
    for url in urls:
        name = list_name(url)
        try:
            result = fetch_list(http, url, etags.get(url))
            if result.error is not None:
                # Keep the old ETag: nothing changed on our side.
                report.errors.append(result.error)
                continue
            if result.not_modified:
                # Unchanged means still listed: mark those postings seen, or
                # housekeeping would delete a list's rows after 90 days of 304s.
                refresh_unchanged(db, result, now)
            else:
                stats = ingest(db, result, now, ranker=ranking.current(db))
                report.added += stats.added
                report.closed += stats.closed
            if result.etag:
                etags[url] = result.etag
            else:
                etags.pop(url, None)
        except Exception as exc:  # noqa: BLE001 - one source never stops the scan
            db.rollback()
            logger.exception("scan of %s failed", name)
            report.errors.append(_unexpected(name, exc))
            # Download it in full next time.
            etags.pop(url, None)


def _still_watched(db: Session, company_id: int) -> bool:
    return db.scalar(select(WatchCompany.id).where(WatchCompany.id == company_id)) is not None


def _scan_boards(
    db: Session,
    http: DiscoveryHttp,
    keywords: list[str],
    now: datetime,
    pause: Callable[[float], None],
    ranking: _Ranking,
    report: ScanReport,
) -> None:
    companies = list(db.scalars(select(WatchCompany).order_by(WatchCompany.id)))
    targets = [(c, c.id, company_name(c)) for c in companies]
    for index, (company, company_id, name) in enumerate(targets):
        if index:
            pause(BOARD_PAUSE)
        error: str | None
        failure: BaseException | None = None
        try:
            result = fetch_board(http, company, keywords, now=now, pause=pause)
            error = result.error
            if error is None:
                stats = ingest(db, result, now, watch_company_id=company_id, ranker=ranking.current(db))
                report.added += stats.added
                report.closed += stats.closed
        except Exception as exc:  # noqa: BLE001 - one source never stops the scan
            db.rollback()
            failure, error = exc, _unexpected(name, exc)
        if error is not None and not _still_watched(db, company_id):
            # Removed from the watchlist mid-scan: the failure (a foreign key
            # on its postings, say) is that removal, so this is a skip, and
            # there is nothing left to record an error on either way.
            logger.info("skipped %s: removed from the watchlist during the scan", name)
            continue
        if failure is not None:
            logger.error("scan of %s failed", name, exc_info=failure)
        if error is not None:
            report.errors.append(error)
        try:
            company.last_checked_at = now
            company.last_error = error
            db.commit()
        except Exception:  # noqa: BLE001 - e.g. the company was removed mid-scan
            db.rollback()
            if _still_watched(db, company_id):
                logger.exception("could not record the scan of %s", name)
            else:
                logger.info("%s was removed from the watchlist during the scan", name)


def _scan(
    db: Session, http: DiscoveryHttp, now: datetime, pause: Callable[[float], None]
) -> ScanReport:
    settings = get_settings(db)
    urls = list(settings.discovery_list_urls)
    keywords = list(settings.discovery_watchlist_keywords)
    stored: dict[str, Any] = dict(settings.discovery_list_etags or {})
    # ETags of lists no longer configured are dropped.
    etags = {u: e for u, e in stored.items() if u in urls and isinstance(e, str) and e}

    ranking = _Ranking()

    report = ScanReport()
    _scan_lists(db, http, urls, etags, now, ranking, report)
    _scan_boards(db, http, keywords, now, pause, ranking, report)
    try:
        report.removed = housekeep(db, now)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("housekeeping failed")
        report.errors.append(_unexpected("Housekeeping", exc))
    try:
        _rescore_if_due(db, now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("re-scoring failed")
        report.errors.append(_unexpected("Re-scoring", exc))

    settings = get_settings(db)
    settings.discovery_list_etags = etags
    settings.last_scan_at = now
    settings.last_scan_error = _summary(report.errors)
    db.commit()
    for error in report.errors:
        logger.warning("scan error: %s", error)
    return report


def run_scan(
    db: Session,
    http: DiscoveryHttp,
    now: datetime | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> ScanReport | None:
    """Scan every list and watched board. Returns None, having read and
    written nothing, when another scan holds the lock."""
    with _lock_connection(db) as conn:
        if not _try_lock(conn):
            return None
        try:
            return _scan(db, http, now or datetime.now(UTC), pause)
        finally:
            _unlock(conn)


def scan_status(db: Session) -> dict[str, Any]:
    """For the Discover header: the last scan, whether one is running now,
    and how many postings the Inbox shows."""
    settings = get_settings(db)
    return {
        "last_scan_at": settings.last_scan_at,
        "last_scan_error": settings.last_scan_error,
        "scanning": is_scan_running(db),
        "inbox_count": match_count(db, filters_from_settings(settings)),
    }
