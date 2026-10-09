from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_sheet_sync_scheduler
from app.db.session import get_db
from app.models.application import ApplicationStatus
from app.schemas.application import (
    ActivityEntryOut,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    StatusHistoryOut,
)
from app.schemas.prep_brief import PrepBriefOut
from app.schemas.research_queue import QueueItemOut
from app.services import application_service, prep_brief_service
from app.services.errors import AlreadyQueuedError, ApplicationNotFoundError, PrepBriefNotFoundError
from app.services.sheet_sync_service import TAB_APPLICATIONS, SheetSyncScheduler

router = APIRouter(
    prefix="/api/applications",
    tags=["applications"],
    dependencies=[Depends(get_current_user)],
)


class StatusChange(BaseModel):
    new_status: ApplicationStatus


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="application not found")


@router.get("", response_model=list[ApplicationOut])
def list_applications(include_archived: bool = False, db: Session = Depends(get_db)):
    return application_service.list_applications(db, include_archived=include_archived)


@router.post("", response_model=ApplicationOut, status_code=201)
def create_application(
    data: ApplicationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    application = application_service.create_application(db, data)
    sync.schedule(background_tasks, [TAB_APPLICATIONS])
    return application


# Must be declared before "/{application_id}" or "activity" is parsed as an id.
@router.get("/activity", response_model=list[ActivityEntryOut])
def recent_activity(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    return application_service.get_recent_activity(db, limit=limit)


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(application_id: int, db: Session = Depends(get_db)):
    try:
        return application_service.get_application(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    data: ApplicationUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        application = application_service.update_application(db, application_id, data)
    except ApplicationNotFoundError:
        raise _not_found()
    sync.schedule(background_tasks, [TAB_APPLICATIONS])
    return application


@router.post("/{application_id}/status", response_model=ApplicationOut)
def change_status(
    application_id: int,
    body: StatusChange,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        application = application_service.change_status(db, application_id, body.new_status)
    except ApplicationNotFoundError:
        raise _not_found()
    sync.schedule(background_tasks, [TAB_APPLICATIONS])
    return application


@router.post("/{application_id}/archive", response_model=ApplicationOut)
def archive_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        application = application_service.archive_application(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()
    sync.schedule(background_tasks, [TAB_APPLICATIONS])
    return application


@router.get("/{application_id}/history", response_model=list[StatusHistoryOut])
def status_history(application_id: int, db: Session = Depends(get_db)):
    try:
        application_service.get_application(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()
    return application_service.get_status_history(db, application_id)


@router.get("/{application_id}/brief", response_model=PrepBriefOut)
def get_brief(application_id: int, db: Session = Depends(get_db)):
    try:
        return prep_brief_service.get_brief(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()
    except PrepBriefNotFoundError:
        raise HTTPException(status_code=404, detail="brief not found")


@router.post("/{application_id}/brief/request", response_model=QueueItemOut, status_code=201)
def request_brief(application_id: int, db: Session = Depends(get_db)):
    """Asks the daily Claude job for a company brief (Phase 4 spec §4)."""
    try:
        return prep_brief_service.request_brief(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()
    except AlreadyQueuedError:
        raise HTTPException(status_code=409, detail="brief already requested")
