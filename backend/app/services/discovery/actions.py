"""Posting actions and paste-a-link (Phase 2 spec §2c, §7; plan Task 8).

Every state change sets `state_changed_at`. Each action locks the posting's
row (`SELECT ... FOR UPDATE`) before reading its state, so two requests on
the same posting run one after the other: a double-clicked Apply creates one
application, and a Dismiss cannot undo an Apply that committed meanwhile.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.posting import Posting, PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.schemas.application import ApplicationCreate
from app.schemas.discovery import PasteConfirmIn, PastePreviewOut
from app.services.application_service import add_application
from app.services.discovery.http import DiscoveryHttp
from app.services.discovery.ingest import ranker_from_settings
from app.services.discovery.labels import application_source
from app.services.discovery.ranking import RESCORED_STATES, apply_score
from app.services.discovery.sources import fetch_pasted
from app.services.discovery.urls import normalize_url, parse_job_url, safe_http_url
from app.services.errors import InvalidPostingStateError, PostingNotFoundError

_VERBS = {
    PostingState.SAVED: "save",
    PostingState.DISMISSED: "dismiss",
    PostingState.NEW: "restore",
}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _lock(db: Session, posting_id: int) -> Posting:
    # populate_existing: a row already in the session gets the values read
    # under the lock, not the ones it loaded before.
    posting = db.scalars(
        select(Posting)
        .where(Posting.id == posting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if posting is None:
        raise PostingNotFoundError(posting_id)
    return posting


def _is_applied(posting: Posting) -> bool:
    """Applied with a live application. An applied posting whose application
    was deleted (`application_id` nulled by the FK) may be saved or applied again."""
    return posting.state is PostingState.APPLIED and posting.application_id is not None


def _invalid(posting: Posting, verb: str, target: PostingState | None = None) -> InvalidPostingStateError:
    state = posting.state
    if state is PostingState.APPLIED:
        message = "already applied"
    elif state is target and target is not PostingState.NEW:
        message = f"already {state.value}"
    else:
        message = f"can't {verb} a posting that is {state.value}"
    return InvalidPostingStateError(message, state=state.value)


def _transition(
    db: Session,
    posting_id: int,
    allowed: tuple[PostingState, ...],
    target: PostingState,
    now: datetime | None,
) -> Posting:
    posting = _lock(db, posting_id)
    if posting.state not in allowed:
        error = _invalid(posting, _VERBS[target], target)
        db.rollback()  # release the row lock
        raise error
    posting.state = target
    posting.state_changed_at = _now(now)
    if target in RESCORED_STATES:
        # A dismissed posting missed preference re-scores (spec §4).
        apply_score(posting, ranker_from_settings(db), posting.state_changed_at)
    db.commit()
    return posting


def save(db: Session, posting_id: int, now: datetime | None = None) -> Posting:
    """Inbox or Dismissed → Saved."""
    return _transition(
        db, posting_id, (PostingState.NEW, PostingState.DISMISSED), PostingState.SAVED, now
    )


def dismiss(db: Session, posting_id: int, now: datetime | None = None) -> Posting:
    """Inbox or Saved → Dismissed (Saved's "Remove")."""
    return _transition(
        db, posting_id, (PostingState.NEW, PostingState.SAVED), PostingState.DISMISSED, now
    )


def restore(db: Session, posting_id: int, now: datetime | None = None) -> Posting:
    """Dismissed → back to new (the Inbox, if it passes the filters)."""
    return _transition(db, posting_id, (PostingState.DISMISSED,), PostingState.NEW, now)


def dismiss_many(db: Session, ids: list[int], now: datetime | None = None) -> int:
    """"Dismiss all shown": dismisses the given postings that are still new;
    others are left alone. Returns how many were dismissed."""
    wanted = sorted(set(ids))
    if not wanted:
        return 0
    result = db.execute(
        update(Posting)
        .where(Posting.id.in_(wanted), Posting.state == PostingState.NEW)
        .values(state=PostingState.DISMISSED, state_changed_at=_now(now))
        .execution_options(synchronize_session="fetch")
    )
    db.commit()
    return result.rowcount


def apply(
    db: Session, posting_id: int, today: date, now: datetime | None = None
) -> Application:
    """Saved or Inbox → Applied: creates an Applied application dated `today`
    through the same path as `create_application` (history row and the
    company-contacts queue item), links it, and saves both together."""
    posting = _lock(db, posting_id)
    allowed = posting.state in (PostingState.NEW, PostingState.SAVED) or (
        posting.state is PostingState.APPLIED and posting.application_id is None
    )
    if not allowed:
        error = _invalid(posting, "apply to")
        db.rollback()
        raise error
    application = add_application(
        db,
        ApplicationCreate(
            company=posting.company,
            role_title=posting.title,
            status=ApplicationStatus.APPLIED,
            date_applied=today,
            location=posting.locations[0] if posting.locations else None,
            job_link=posting.url,
            source=application_source(posting.source),
        ),
    )
    posting.state = PostingState.APPLIED
    posting.application_id = application.id
    posting.state_changed_at = _now(now)
    db.commit()
    return application


# --- paste a link ------------------------------------------------------------


@dataclass(frozen=True)
class _Identity:
    """How a pasted URL is stored: the board's own key for a recognized job
    link (as the board scan keys it), else PASTED keyed by the url_key."""

    source: PostingSource
    source_key: str
    url_key: str
    ats: WatchAts | None = None
    board_token: str | None = None


def _identify(url: str) -> _Identity:
    url_key = normalize_url(url)
    if url_key is None:  # callers pass only safe_http_url output
        raise ValueError("not an http(s) URL")
    ref = parse_job_url(url)
    if ref is None:
        return _Identity(PostingSource.PASTED, url_key, url_key)
    # Workday: "<host>/<tenant>/<site>" + "/" + "job/...", which is what
    # parsers.workday_source_key builds for the same job.
    key = f"{ref.token}/{ref.job_id}" if ref.ats is WatchAts.WORKDAY else ref.job_id
    return _Identity(PostingSource(ref.ats.value), key, url_key, ref.ats, ref.token)


def _stored(db: Session, ident: _Identity, *, lock: bool = False) -> list[Posting]:
    """Postings already stored for this URL: the same board job, or the same
    url_key. The same-job match comes first, since an insert would collide with it."""
    query = (
        select(Posting)
        .where(
            or_(
                Posting.url_key == ident.url_key,
                (Posting.source == ident.source) & (Posting.source_key == ident.source_key),
            )
        )
        .order_by(Posting.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rows = list(db.scalars(query))
    rows.sort(key=lambda p: not (p.source == ident.source and p.source_key == ident.source_key))
    return rows


def _blocking(rows: list[Posting]) -> InvalidPostingStateError | None:
    """Pasting a posting that is already applied for or saved is refused at preview."""
    for row in rows:
        if _is_applied(row):
            return InvalidPostingStateError("already applied", state=row.state.value)
    for row in rows:
        if row.state is PostingState.SAVED:
            return InvalidPostingStateError("already saved", state=row.state.value)
    return None


def _preview_of(posting: Posting) -> PastePreviewOut:
    return PastePreviewOut(
        company=posting.company,
        title=posting.title,
        locations=list(posting.locations),
        url=posting.url,
        date_posted=posting.date_posted,
        source=posting.source,
    )


def paste_preview(
    db: Session, http: DiscoveryHttp, url: str, now: datetime | None = None
) -> PastePreviewOut:
    """Editable details for a pasted link (spec §2c). Never writes.

    A URL whose posting is already saved or applied for is refused. One that
    is stored as new or dismissed (say, a list posting the filters hide) is
    previewed from the stored row, with no request; confirming moves it to
    Saved. Anything else is fetched (`fetch_pasted` raises
    `DiscoveryFetchError` with a readable message for bad or failing links)."""
    safe = safe_http_url(url) if isinstance(url, str) else None
    if safe is None:
        return _fetch_preview(http, url, now)  # raises the readable error
    rows = _stored(db, _identify(safe))
    if (error := _blocking(rows)) is not None:
        raise error
    if rows:
        return _preview_of(rows[0])
    return _fetch_preview(http, safe, now)


def _fetch_preview(http: DiscoveryHttp, url: str, now: datetime | None) -> PastePreviewOut:
    details = fetch_pasted(http, url, now=now)
    return PastePreviewOut(
        company=details.company,
        title=details.title,
        locations=details.locations,
        url=url.strip(),
        date_posted=details.date_posted,
        source=details.source,
    )


def _watch_company_id(db: Session, ident: _Identity) -> int | None:
    if ident.ats is None:
        return None
    return db.scalar(
        select(WatchCompany.id).where(
            WatchCompany.ats == ident.ats, WatchCompany.board_token == ident.board_token
        )
    )


def _save_stored(rows: list[Posting], data: PasteConfirmIn, now: datetime) -> Posting:
    if any(_is_applied(row) for row in rows):
        raise InvalidPostingStateError("already applied", state=PostingState.APPLIED.value)
    saved = [row for row in rows if row.state is PostingState.SAVED]
    posting = saved[0] if saved else rows[0]
    # The user confirmed these fields in the preview. A later scan of the
    # posting's source refreshes them from the source again.
    posting.company = data.company
    posting.title = data.title
    posting.locations = list(data.locations)
    if data.date_posted is not None:
        posting.date_posted = data.date_posted
    if posting.state is not PostingState.SAVED:
        posting.state = PostingState.SAVED
        posting.state_changed_at = now
    return posting


def paste_confirm(db: Session, data: PasteConfirmIn, now: datetime | None = None) -> Posting:
    """Save a pasted posting (spec §2c): it skips the filters and goes straight
    to Saved. If the posting is already stored (same board job or same
    url_key), that row moves to Saved instead of a new one being inserted;
    an applied one raises `InvalidPostingStateError("already applied")`."""
    now = _now(now)
    url = safe_http_url(data.url)
    if url is None:  # PasteConfirmIn already checks this
        raise ValueError("not an http(s) URL")
    ident = _identify(url)
    ranker = ranker_from_settings(db)
    for attempt in range(2):
        rows = _stored(db, ident, lock=True)
        if rows:
            try:
                posting = _save_stored(rows, data, now)
            except InvalidPostingStateError:
                db.rollback()
                raise
            apply_score(posting, ranker, now)
            db.commit()
            return posting
        posting = Posting(
            source=ident.source,
            source_key=ident.source_key,
            company=data.company,
            title=data.title,
            locations=list(data.locations),
            url=url,
            url_key=ident.url_key,
            terms=[],
            date_posted=data.date_posted,
            first_seen_at=now,
            last_seen_at=now,
            closed=False,
            state=PostingState.SAVED,
            state_changed_at=now,
            watch_company_id=_watch_company_id(db, ident),
        )
        apply_score(posting, ranker, now)
        db.add(posting)
        try:
            db.commit()
        except IntegrityError:
            # Another request stored the same board job meanwhile: use that row.
            db.rollback()
            if attempt:
                raise
            continue
        return posting
    raise AssertionError("unreachable")
