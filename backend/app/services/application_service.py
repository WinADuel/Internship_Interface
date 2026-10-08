from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.status_history import StatusHistory
from app.schemas.application import ApplicationCreate, ApplicationUpdate
from app.services.errors import AlreadyQueuedError, ApplicationNotFoundError
from app.services.research_queue_service import add_company_contacts_item


def _now() -> datetime:
    # Explicit timestamp: the column's now() default is constant within a
    # transaction, which would make same-transaction changes unorderable.
    return datetime.now(timezone.utc)


def _enqueue_contacts_if_applied(db: Session, application: Application) -> None:
    """Spec §13.2: entering `applied` queues a find-contacts request, once.
    Runs before the caller's commit, so the status change and the queue
    item are saved together."""
    if application.status != ApplicationStatus.APPLIED:
        return
    try:
        add_company_contacts_item(db, application)
    except AlreadyQueuedError:
        pass


def create_application(db: Session, data: ApplicationCreate) -> Application:
    application = Application(**data.model_dump())
    db.add(application)
    db.flush()  # assign application.id for the history row
    db.add(
        StatusHistory(
            application_id=application.id,
            old_status=None,
            new_status=application.status,
            changed_at=_now(),
        )
    )
    _enqueue_contacts_if_applied(db, application)
    db.commit()
    return application


def get_application(db: Session, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise ApplicationNotFoundError(application_id)
    return application


def list_applications(db: Session, include_archived: bool = False) -> list[Application]:
    query = select(Application).order_by(Application.id)
    if not include_archived:
        query = query.where(Application.archived.is_(False))
    return list(db.scalars(query))


def update_application(db: Session, application_id: int, data: ApplicationUpdate) -> Application:
    """Apply the provided fields. Status is changed only via `change_status`,
    so history stays complete; a `status` in `data` is routed there."""
    application = get_application(db, application_id)
    fields = data.model_dump(exclude_unset=True)
    new_status = fields.pop("status", None)
    for name, value in fields.items():
        setattr(application, name, value)
    db.commit()
    if new_status is not None:
        return change_status(db, application_id, new_status)
    return application


def change_status(db: Session, application_id: int, new_status: ApplicationStatus) -> Application:
    """Move an application to `new_status`, recording a history row.

    A change to the current status is a no-op (no history row).
    """
    application = get_application(db, application_id)
    if new_status == application.status:
        return application
    db.add(
        StatusHistory(
            application_id=application.id,
            old_status=application.status,
            new_status=new_status,
            changed_at=_now(),
        )
    )
    application.status = new_status
    _enqueue_contacts_if_applied(db, application)
    db.commit()
    return application


def archive_application(db: Session, application_id: int) -> Application:
    application = get_application(db, application_id)
    application.archived = True
    db.commit()
    return application


def get_status_history(db: Session, application_id: int) -> list[StatusHistory]:
    return list(
        db.scalars(
            select(StatusHistory)
            .where(StatusHistory.application_id == application_id)
            .order_by(StatusHistory.changed_at, StatusHistory.id)
        )
    )


def get_recent_activity(db: Session, limit: int = 10) -> list[dict]:
    rows = db.execute(
        select(StatusHistory, Application)
        .join(Application, Application.id == StatusHistory.application_id)
        .order_by(StatusHistory.changed_at.desc(), StatusHistory.id.desc())
        .limit(limit)
    )
    return [
        {
            "application_id": app.id,
            "company": app.company,
            "role_title": app.role_title,
            "old_status": history.old_status,
            "new_status": history.new_status,
            "changed_at": history.changed_at,
        }
        for history, app in rows
    ]
