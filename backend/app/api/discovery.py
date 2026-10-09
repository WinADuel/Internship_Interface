"""Job discovery routes (Phase 2 spec §7-§8, plan Task 9): the Discover
tabs, posting actions, paste-a-link, the watchlist, Scan now, the scan
status and the live match count. Thin: the work is in
`app.services.discovery`."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_discovery_http,
    get_scan_session_factory,
    get_sheet_sync_scheduler,
)
from app.db.session import get_db
from app.models.posting import Posting
from app.schemas.application import ApplicationOut
from app.schemas.discovery import (
    DismissAllIn,
    DismissAllOut,
    MatchCountIn,
    MatchCountOut,
    PasteConfirmIn,
    PasteIn,
    PastePreviewOut,
    PostingOut,
    PostingPage,
    ScanStartedOut,
    ScanStatusOut,
    TopPicksCountIn,
    WatchCompanyIn,
    WatchCompanyOut,
)
from app.services.discovery import actions, watchlist
from app.services.discovery.filters import (
    filters_from_settings,
    list_postings,
    match_count,
    top_picks_count,
    top_picks_preview,
)
from app.services.discovery.http import DiscoveryFetchError, DiscoveryHttp
from app.services.discovery.scanner import is_scan_running, run_scan, scan_status
from app.services.errors import (
    DuplicateWatchCompanyError,
    InvalidPostingStateError,
    PostingNotFoundError,
    UnsupportedCareersSiteError,
    WatchCompanyNotFoundError,
)
from app.services.nudges import utc_today
from app.services.settings_service import get_settings
from app.services.sheet_sync_service import (
    TAB_APPLICATIONS,
    TAB_SAVED_POSTINGS,
    SheetSyncScheduler,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/discovery",
    tags=["discovery"],
    dependencies=[Depends(get_current_user)],
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _posting_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="posting not found")


def _conflict(exc: InvalidPostingStateError) -> HTTPException:
    return HTTPException(status_code=409, detail=exc.message)


# --- postings ----------------------------------------------------------------


def _out(db: Session, posting: Posting) -> PostingOut:
    return PostingOut.build(posting, get_settings(db).ranking_updated_at)


@router.get("/postings", response_model=PostingPage)
def get_postings(
    view: Literal["inbox", "saved", "dismissed"] = "inbox",
    sort: Literal["best", "newest"] = "best",
    min_score: int | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """`sort` and `min_score` (Top picks) apply to the Inbox only."""
    settings = get_settings(db)
    filters = filters_from_settings(settings)
    items, total = list_postings(
        db, view, filters, limit=limit, offset=offset, sort=sort, min_score=min_score
    )
    return PostingPage(
        items=[PostingOut.build(p, settings.ranking_updated_at) for p in items],
        total=total,
        top_picks=top_picks_count(db, filters) if view == "inbox" else None,
    )


@router.post("/postings/dismiss-all", response_model=DismissAllOut)
def dismiss_all(
    body: DismissAllIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    dismissed = actions.dismiss_many(db, body.ids)
    sync.schedule(background_tasks, [TAB_SAVED_POSTINGS])
    return DismissAllOut(dismissed=dismissed)


def _change_state(
    action: Callable[[Session, int], object],
    posting_id: int,
    db: Session,
    background_tasks: BackgroundTasks,
    sync: SheetSyncScheduler,
):
    try:
        posting = action(db, posting_id)
    except PostingNotFoundError:
        raise _posting_not_found() from None
    except InvalidPostingStateError as exc:
        raise _conflict(exc) from None
    sync.schedule(background_tasks, [TAB_SAVED_POSTINGS])
    return _out(db, posting)


@router.post("/postings/{posting_id}/save", response_model=PostingOut)
def save_posting(
    posting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    return _change_state(actions.save, posting_id, db, background_tasks, sync)


@router.post("/postings/{posting_id}/dismiss", response_model=PostingOut)
def dismiss_posting(
    posting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    return _change_state(actions.dismiss, posting_id, db, background_tasks, sync)


@router.post("/postings/{posting_id}/restore", response_model=PostingOut)
def restore_posting(
    posting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    return _change_state(actions.restore, posting_id, db, background_tasks, sync)


@router.post("/postings/{posting_id}/apply", response_model=ApplicationOut, status_code=201)
def apply_to_posting(
    posting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        application = actions.apply(db, posting_id, utc_today())
    except PostingNotFoundError:
        raise _posting_not_found() from None
    except InvalidPostingStateError as exc:
        raise _conflict(exc) from None
    sync.schedule(background_tasks, [TAB_APPLICATIONS, TAB_SAVED_POSTINGS])
    return application


# --- paste a link ------------------------------------------------------------


@router.post("/paste/preview", response_model=PastePreviewOut)
def paste_preview(
    body: PasteIn,
    db: Session = Depends(get_db),
    http: DiscoveryHttp = Depends(get_discovery_http),
):
    try:
        return actions.paste_preview(db, http, body.url)
    except InvalidPostingStateError as exc:
        raise _conflict(exc) from None
    except DiscoveryFetchError as exc:
        # User-safe by construction: never a response body or query string.
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/paste", response_model=PostingOut, status_code=201)
def paste_confirm(
    body: PasteConfirmIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        posting = actions.paste_confirm(db, body)
    except InvalidPostingStateError as exc:
        raise _conflict(exc) from None
    sync.schedule(background_tasks, [TAB_SAVED_POSTINGS])
    return _out(db, posting)


# --- watchlist ---------------------------------------------------------------


@router.get("/watchlist", response_model=list[WatchCompanyOut])
def get_watchlist(db: Session = Depends(get_db)):
    filters = filters_from_settings(get_settings(db))
    return [WatchCompanyOut.build(c, n) for c, n in watchlist.list_companies(db, filters)]


@router.post("/watchlist", response_model=WatchCompanyOut, status_code=201)
def add_to_watchlist(body: WatchCompanyIn, db: Session = Depends(get_db)):
    try:
        company = watchlist.add_company(db, body)
    except UnsupportedCareersSiteError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None
    except DuplicateWatchCompanyError:
        raise HTTPException(
            status_code=409, detail="that company is already on the watchlist"
        ) from None
    # Postings are linked to a company only by scans after this, so none match yet.
    return WatchCompanyOut.build(company, 0)


@router.delete("/watchlist/{company_id}", status_code=204)
def remove_from_watchlist(company_id: int, db: Session = Depends(get_db)):
    try:
        watchlist.remove_company(db, company_id)
    except WatchCompanyNotFoundError:
        raise HTTPException(status_code=404, detail="watched company not found") from None
    return Response(status_code=204)


# --- scan, status, match count -----------------------------------------------


def _scan_in_background(open_session: SessionFactory, http: DiscoveryHttp) -> None:
    """Scan now's background task. Runs after the response in a session of
    its own. A scan that started meanwhile makes `run_scan` return None."""
    try:
        with open_session() as db:
            run_scan(db, http)
    except Exception:  # noqa: BLE001 - nobody is waiting on this task
        logger.exception("scan failed")


@router.post("/scan", response_model=ScanStartedOut, status_code=202)
def start_scan(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    http: DiscoveryHttp = Depends(get_discovery_http),
    open_session: SessionFactory = Depends(get_scan_session_factory),
):
    if is_scan_running(db):
        raise HTTPException(status_code=409, detail="already scanning")
    background_tasks.add_task(_scan_in_background, open_session, http)
    return ScanStartedOut(started=True)


@router.get("/status", response_model=ScanStatusOut)
def get_status(db: Session = Depends(get_db)):
    return ScanStatusOut(**scan_status(db))


@router.post("/match-count", response_model=MatchCountOut)
def get_match_count(body: MatchCountIn, db: Session = Depends(get_db)):
    return MatchCountOut(count=match_count(db, body.to_filters()))


@router.post("/top-picks-count", response_model=MatchCountOut)
def get_top_picks_count(body: TopPicksCountIn, db: Session = Depends(get_db)):
    """Top picks the Inbox (saved filters) would have with the unsaved
    ranking preferences in the body: Settings → Ranking's live count."""
    filters = filters_from_settings(get_settings(db))
    return MatchCountOut(count=top_picks_preview(db, filters, body.to_prefs(), datetime.now(UTC)))
