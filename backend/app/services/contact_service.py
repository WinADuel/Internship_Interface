from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.contact import Contact, ContactKind, ContactOrigin, ContactStatus
from app.models.contact_status_history import ContactStatusHistory
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.contact_transitions import (
    ACTION_DATE_FIELD,
    ACTION_RESULT,
    ACTIONS_BY_STATUS,
    NO_RESPONSE_REASON,
    STATUS_DATE_FIELD,
    UNDO_WINDOW,
    ContactAction,
)
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    InvalidTransitionError,
    UndoExpiredError,
)
from app.services.nudges import NudgeKind, compute_nudge
from app.services.settings_service import get_settings, nudge_settings

_DRAFT_FIELDS = ("draft_subject", "draft_body")
_FOLLOWUP_FIELDS = ("followup_subject", "followup_body")


def _now() -> datetime:
    # Explicit timestamp, as in application_service: now() is constant per transaction.
    return datetime.now(timezone.utc)


def _check_application(db: Session, application_id: int | None) -> None:
    if application_id is not None and db.get(Application, application_id) is None:
        raise ApplicationNotFoundError(application_id)


def create_contact(db: Session, data: ContactCreate) -> Contact:
    _check_application(db, data.application_id)
    contact = Contact(**data.model_dump(), origin=ContactOrigin.MANUAL)
    db.add(contact)
    db.commit()
    return contact


def get_contact(db: Session, contact_id: int) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise ContactNotFoundError(contact_id)
    return contact


def list_contacts(
    db: Session,
    kind: ContactKind | None = None,
    include_archived: bool = False,
    application_id: int | None = None,
) -> list[Contact]:
    query = select(Contact).order_by(Contact.updated_at.desc(), Contact.id.desc())
    if kind is not None:
        query = query.where(Contact.kind == kind)
    if not include_archived:
        query = query.where(Contact.archived.is_(False))
    if application_id is not None:
        query = query.where(Contact.application_id == application_id)
    return list(db.scalars(query))


def update_contact(db: Session, contact_id: int, data: ContactUpdate) -> Contact:
    """Apply the provided fields. Editing a draft marks it user-owned, so the
    Claude job never overwrites it (spec §13.2)."""
    contact = get_contact(db, contact_id)
    fields = data.model_dump(exclude_unset=True)
    if "application_id" in fields:
        _check_application(db, fields["application_id"])
    for name, value in fields.items():
        setattr(contact, name, value)
    if any(f in fields for f in _DRAFT_FIELDS):
        contact.draft_edited = True
    if any(f in fields for f in _FOLLOWUP_FIELDS):
        contact.followup_edited = True
    db.commit()
    return contact


def apply_action(
    db: Session,
    contact_id: int,
    action: ContactAction,
    on: datetime | None = None,
    meeting_at: datetime | None = None,
    now: datetime | None = None,
) -> Contact:
    """Run one status button (spec §13.3). Invalid actions raise before any write."""
    contact = get_contact(db, contact_id)
    if action not in ACTIONS_BY_STATUS[contact.status]:
        raise InvalidTransitionError(
            f"cannot apply '{action.value}' to a contact with status '{contact.status.value}'"
        )
    if action == ContactAction.MEETING_SET and meeting_at is None:
        raise InvalidTransitionError("meeting_set requires meeting_at")
    now = now or _now()
    old_status = contact.status
    contact.status = ACTION_RESULT[action]
    date_field = ACTION_DATE_FIELD.get(action)
    if date_field is not None:
        setattr(contact, date_field, meeting_at if action == ContactAction.MEETING_SET else (on or now))
    if action == ContactAction.NO_RESPONSE:
        contact.closed_reason = NO_RESPONSE_REASON
    contact.nudge_snoozed_until = None
    db.add(
        ContactStatusHistory(
            contact_id=contact.id, old_status=old_status, new_status=contact.status, changed_at=now
        )
    )
    db.commit()
    return contact


def move_status(
    db: Session, contact_id: int, new_status: ContactStatus, now: datetime | None = None
) -> Contact:
    """Kanban drag: allowed only where a button would make the same move.
    A meeting needs a time, so it must go through the button."""
    contact = get_contact(db, contact_id)
    action = next(
        (a for a in ACTIONS_BY_STATUS[contact.status] if ACTION_RESULT[a] == new_status), None
    )
    if action is None:
        raise InvalidTransitionError(
            f"cannot move a contact from '{contact.status.value}' to '{new_status.value}'"
        )
    if action == ContactAction.MEETING_SET:
        raise InvalidTransitionError("use the Meeting set button to record the meeting time")
    return apply_action(db, contact_id, action, now=now)


def undo_last_action(db: Session, contact_id: int, now: datetime | None = None) -> Contact:
    contact = get_contact(db, contact_id)
    now = now or _now()
    last = db.scalars(
        select(ContactStatusHistory)
        .where(ContactStatusHistory.contact_id == contact_id)
        .order_by(ContactStatusHistory.changed_at.desc(), ContactStatusHistory.id.desc())
        .limit(1)
    ).first()
    if last is None or last.old_status is None or now - last.changed_at > UNDO_WINDOW:
        raise UndoExpiredError(contact_id)
    date_field = STATUS_DATE_FIELD.get(last.new_status)
    if date_field is not None:
        setattr(contact, date_field, None)
    if contact.closed_reason == NO_RESPONSE_REASON:
        contact.closed_reason = None
    contact.status = last.old_status
    db.delete(last)
    db.commit()
    return contact


def snooze_contact(db: Session, contact_id: int, days: int, today: date) -> Contact:
    contact = get_contact(db, contact_id)
    contact.nudge_snoozed_until = today + timedelta(days=days)
    db.commit()
    return contact


def archive_contact(db: Session, contact_id: int) -> Contact:
    contact = get_contact(db, contact_id)
    contact.archived = True
    db.commit()
    return contact


def get_contact_history(db: Session, contact_id: int) -> list[ContactStatusHistory]:
    return list(
        db.scalars(
            select(ContactStatusHistory)
            .where(ContactStatusHistory.contact_id == contact_id)
            .order_by(ContactStatusHistory.changed_at, ContactStatusHistory.id)
        )
    )


def get_recent_contact_activity(db: Session, limit: int = 10) -> list[dict]:
    rows = db.execute(
        select(ContactStatusHistory, Contact)
        .join(Contact, Contact.id == ContactStatusHistory.contact_id)
        .order_by(ContactStatusHistory.changed_at.desc(), ContactStatusHistory.id.desc())
        .limit(limit)
    )
    return [
        {
            "contact_id": contact.id,
            "name": contact.name,
            "organization": contact.organization,
            "kind": contact.kind,
            "old_status": history.old_status,
            "new_status": history.new_status,
            "changed_at": history.changed_at,
        }
        for history, contact in rows
    ]


def last_status_changes(db: Session) -> dict[int, datetime]:
    """Newest history timestamp per contact, in one grouped query."""
    rows = db.execute(
        select(ContactStatusHistory.contact_id, func.max(ContactStatusHistory.changed_at)).group_by(
            ContactStatusHistory.contact_id
        )
    )
    return {contact_id: changed_at for contact_id, changed_at in rows}


def list_needs_attention(db: Session, today: date) -> list[tuple[Contact, NudgeKind]]:
    settings = nudge_settings(get_settings(db))
    last_changes = last_status_changes(db)
    result = []
    for contact in list_contacts(db):
        nudge = compute_nudge(contact, last_changes.get(contact.id), settings, today)
        if nudge is not None:
            result.append((contact, nudge))
    return result


def contact_nudges(db: Session, contacts: list[Contact], today: date) -> dict[int, NudgeKind | None]:
    """Nudge per contact id, for filling `ContactOut.nudge` on reads."""
    settings = nudge_settings(get_settings(db))
    if len(contacts) == 1:
        last = db.scalar(
            select(func.max(ContactStatusHistory.changed_at)).where(
                ContactStatusHistory.contact_id == contacts[0].id
            )
        )
        last_changes = {contacts[0].id: last}
    else:
        last_changes = last_status_changes(db)
    return {c.id: compute_nudge(c, last_changes.get(c.id), settings, today) for c in contacts}
