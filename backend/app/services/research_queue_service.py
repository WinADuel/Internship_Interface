from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.schemas.research_queue import QueueItemCreate
from app.services.errors import AlreadyQueuedError, QueueItemNotFoundError, QueueItemNotPendingError

COMPANY_CONTACTS_TARGET = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_professor(db: Session, data: QueueItemCreate) -> ResearchQueueItem:
    kind = QueueKind(data.kind)
    item = ResearchQueueItem(
        kind=kind,
        request_text=data.request_text,
        target_count=1 if kind == QueueKind.PROFESSOR_PERSON else data.target_count,
        created_at=_now(),
    )
    db.add(item)
    db.commit()
    return item


def enqueue_company_contacts(db: Session, application: Application) -> ResearchQueueItem:
    """Queue a find-contacts request; at most one per application, ever."""
    item = add_company_contacts_item(db, application)
    db.commit()
    return item


def add_company_contacts_item(db: Session, application: Application) -> ResearchQueueItem:
    """`enqueue_company_contacts` without the commit, so the application
    service can save a status change and its queue item atomically."""
    existing = db.scalars(
        select(ResearchQueueItem.id).where(ResearchQueueItem.application_id == application.id).limit(1)
    ).first()
    if existing is not None:
        raise AlreadyQueuedError(application.id)
    request_text = f"{application.company} — {application.role_title}"
    if application.job_link:
        request_text += f" — {application.job_link}"
    item = ResearchQueueItem(
        kind=QueueKind.COMPANY_CONTACTS,
        request_text=request_text,
        application_id=application.id,
        target_count=COMPANY_CONTACTS_TARGET,
        created_at=_now(),
    )
    db.add(item)
    db.flush()
    return item


def list_queue(db: Session, state: QueueState | None = None) -> list[ResearchQueueItem]:
    query = select(ResearchQueueItem).order_by(ResearchQueueItem.created_at.desc(), ResearchQueueItem.id.desc())
    if state is not None:
        query = query.where(ResearchQueueItem.state == state)
    return list(db.scalars(query))


def pending_items(db: Session, limit: int) -> list[ResearchQueueItem]:
    """Oldest first, so leftovers from a capped run go first next time."""
    return list(
        db.scalars(
            select(ResearchQueueItem)
            .where(ResearchQueueItem.state == QueueState.PENDING)
            .order_by(ResearchQueueItem.created_at, ResearchQueueItem.id)
            .limit(limit)
        )
    )


def get_item(db: Session, item_id: int) -> ResearchQueueItem:
    item = db.get(ResearchQueueItem, item_id)
    if item is None:
        raise QueueItemNotFoundError(item_id)
    return item


def _finish(db: Session, item_id: int, state: QueueState, note: str, now: datetime | None) -> ResearchQueueItem:
    item = get_item(db, item_id)
    if item.state != QueueState.PENDING:
        raise QueueItemNotPendingError(item_id)
    item.state = state
    item.result_note = note
    item.completed_at = now or _now()
    db.commit()
    return item


def complete_item(db: Session, item_id: int, note: str, now: datetime | None = None) -> ResearchQueueItem:
    return _finish(db, item_id, QueueState.DONE, note, now)


def fail_item(db: Session, item_id: int, note: str, now: datetime | None = None) -> ResearchQueueItem:
    return _finish(db, item_id, QueueState.FAILED, note, now)
