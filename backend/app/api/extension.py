"""The Chrome extension's only way in. Every route is behind
`get_extension_token` (a bearer token made in Settings); nothing here
accepts a session cookie, and the extension can't reach any other route."""

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_discovery_http, get_extension_token, get_sheet_sync_scheduler
from app.db.session import get_db
from app.schemas.apply import ExtensionAppliedOut, ExtensionFillOut, ExtensionUrlIn
from app.services.apply import service
from app.services.discovery.http import DiscoveryHttp
from app.services.nudges import utc_today
from app.services.sheet_sync_service import TAB_APPLICATIONS, TAB_SAVED_POSTINGS, SheetSyncScheduler

router = APIRouter(prefix="/api/extension", tags=["extension"], dependencies=[Depends(get_extension_token)])


@router.get("/ping")
def ping():
    """Lets the extension's options page check the address and token."""
    return {"ok": True}


@router.post("/fill", response_model=ExtensionFillOut)
def fill(
    body: ExtensionUrlIn,
    db: Session = Depends(get_db),
    http: DiscoveryHttp = Depends(get_discovery_http),
):
    """The answers for the application page at `url`: the prepared
    application when the job is saved here, else just the profile."""
    return service.fill_for_url(db, http, body.url)


@router.post("/applied", response_model=ExtensionAppliedOut)
def applied(
    body: ExtensionUrlIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    """The owner submitted the application on the company's page."""
    result = service.mark_applied(db, body.url, utc_today())
    if result.status == "applied":
        sync.schedule(background_tasks, [TAB_APPLICATIONS, TAB_SAVED_POSTINGS])
    return result
