from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.contact import Contact, ContactKind
from app.schemas.contact import (
    ContactActionIn,
    ContactActivityOut,
    ContactCreate,
    ContactHistoryOut,
    ContactOut,
    ContactStatusIn,
    ContactUpdate,
    SnoozeIn,
)
from app.services import contact_service
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    InvalidTransitionError,
    UndoExpiredError,
)

router = APIRouter(
    prefix="/api/contacts",
    tags=["contacts"],
    dependencies=[Depends(get_current_user)],
)

_NOT_FOUND = HTTPException(status_code=404, detail="contact not found")
_BAD_APPLICATION = HTTPException(status_code=422, detail="application not found")


def _out(db: Session, contacts: list[Contact]) -> list[ContactOut]:
    nudges = contact_service.contact_nudges(db, contacts, today=date.today())
    return [ContactOut.model_validate(c).model_copy(update={"nudge": nudges[c.id]}) for c in contacts]


def _one(db: Session, contact: Contact) -> ContactOut:
    return _out(db, [contact])[0]


@router.get("", response_model=list[ContactOut])
def list_contacts(
    kind: ContactKind | None = None,
    include_archived: bool = False,
    application_id: int | None = None,
    db: Session = Depends(get_db),
):
    contacts = contact_service.list_contacts(
        db, kind=kind, include_archived=include_archived, application_id=application_id
    )
    return _out(db, contacts)


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(data: ContactCreate, db: Session = Depends(get_db)):
    try:
        return _one(db, contact_service.create_contact(db, data))
    except ApplicationNotFoundError:
        raise _BAD_APPLICATION


# Static paths must be declared before "/{contact_id}".
@router.get("/activity", response_model=list[ContactActivityOut])
def recent_activity(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    return contact_service.get_recent_contact_activity(db, limit=limit)


@router.get("/needs-attention", response_model=list[ContactOut])
def needs_attention(db: Session = Depends(get_db)):
    items = contact_service.list_needs_attention(db, today=date.today())
    return [ContactOut.model_validate(c).model_copy(update={"nudge": n}) for c, n in items]


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    try:
        return _one(db, contact_service.get_contact(db, contact_id))
    except ContactNotFoundError:
        raise _NOT_FOUND


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, data: ContactUpdate, db: Session = Depends(get_db)):
    try:
        return _one(db, contact_service.update_contact(db, contact_id, data))
    except ContactNotFoundError:
        raise _NOT_FOUND
    except ApplicationNotFoundError:
        raise _BAD_APPLICATION


@router.post("/{contact_id}/actions", response_model=ContactOut)
def apply_action(contact_id: int, body: ContactActionIn, db: Session = Depends(get_db)):
    try:
        contact = contact_service.apply_action(
            db, contact_id, body.action, on=body.on, meeting_at=body.meeting_at
        )
    except ContactNotFoundError:
        raise _NOT_FOUND
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=e.message)
    return _one(db, contact)


@router.post("/{contact_id}/status", response_model=ContactOut)
def move_status(contact_id: int, body: ContactStatusIn, db: Session = Depends(get_db)):
    try:
        contact = contact_service.move_status(db, contact_id, body.new_status)
    except ContactNotFoundError:
        raise _NOT_FOUND
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=e.message)
    return _one(db, contact)


@router.post("/{contact_id}/undo", response_model=ContactOut)
def undo(contact_id: int, db: Session = Depends(get_db)):
    try:
        contact = contact_service.undo_last_action(db, contact_id)
    except ContactNotFoundError:
        raise _NOT_FOUND
    except UndoExpiredError:
        raise HTTPException(status_code=409, detail="undo window expired")
    return _one(db, contact)


@router.post("/{contact_id}/snooze", response_model=ContactOut)
def snooze(contact_id: int, body: SnoozeIn, db: Session = Depends(get_db)):
    try:
        return _one(db, contact_service.snooze_contact(db, contact_id, body.days, today=date.today()))
    except ContactNotFoundError:
        raise _NOT_FOUND


@router.post("/{contact_id}/archive", response_model=ContactOut)
def archive(contact_id: int, db: Session = Depends(get_db)):
    try:
        return _one(db, contact_service.archive_contact(db, contact_id))
    except ContactNotFoundError:
        raise _NOT_FOUND


@router.get("/{contact_id}/history", response_model=list[ContactHistoryOut])
def history(contact_id: int, db: Session = Depends(get_db)):
    try:
        contact_service.get_contact(db, contact_id)
    except ContactNotFoundError:
        raise _NOT_FOUND
    return contact_service.get_contact_history(db, contact_id)
