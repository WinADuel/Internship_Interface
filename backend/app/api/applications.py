from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.application import ApplicationStatus
from app.schemas.application import (
    ActivityEntryOut,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    StatusHistoryOut,
)
from app.services import application_service
from app.services.errors import ApplicationNotFoundError

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
def create_application(data: ApplicationCreate, db: Session = Depends(get_db)):
    return application_service.create_application(db, data)


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
def update_application(application_id: int, data: ApplicationUpdate, db: Session = Depends(get_db)):
    try:
        return application_service.update_application(db, application_id, data)
    except ApplicationNotFoundError:
        raise _not_found()


@router.post("/{application_id}/status", response_model=ApplicationOut)
def change_status(application_id: int, body: StatusChange, db: Session = Depends(get_db)):
    try:
        return application_service.change_status(db, application_id, body.new_status)
    except ApplicationNotFoundError:
        raise _not_found()


@router.post("/{application_id}/archive", response_model=ApplicationOut)
def archive_application(application_id: int, db: Session = Depends(get_db)):
    try:
        return application_service.archive_application(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()


@router.get("/{application_id}/history", response_model=list[StatusHistoryOut])
def status_history(application_id: int, db: Session = Depends(get_db)):
    try:
        application_service.get_application(db, application_id)
    except ApplicationNotFoundError:
        raise _not_found()
    return application_service.get_status_history(db, application_id)
