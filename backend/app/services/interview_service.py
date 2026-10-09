"""Interview rounds (Phase 4 spec §3–§4): CRUD, the default checklist, the
derived `applications.interview_datetime`, interviewer and story links, and
the thank-you-due rule.

Every round write re-derives the application's `interview_datetime` before
committing. Sheet sync needs FastAPI's BackgroundTasks, so, as for
application writes, the route schedules it: `ROUND_SYNC_TABS` after a round
write, plus `CONTACT_TABS` after `set_round_contacts` (it can link a contact
to the application)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.contact import Contact
from app.models.interview import InterviewRound, InterviewState
from app.models.story import Story
from app.schemas.interview import ChecklistItem, InterviewRoundCreate, InterviewRoundUpdate
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    ContactNotOnApplicationError,
    InterviewRoundNotFoundError,
    StoryNotFoundError,
)
from app.services.sheet_sync_service import TAB_APPLICATIONS

# A round write can change the application's derived interview_datetime.
ROUND_SYNC_TABS = (TAB_APPLICATIONS,)

DEFAULT_CHECKLIST = (
    "Research the company and team",
    "Re-read the job description",
    "Pick 2–3 stories",
    "Prepare 3 questions to ask",
    "Test the call link / plan the route",
    "Send thank-you notes within 24 hours",
)

THANK_YOU_WINDOW = timedelta(days=3)

RoundScope = Literal["upcoming", "past", "all"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_item_id() -> str:
    return uuid.uuid4().hex[:12]


def default_checklist() -> list[dict]:
    return [{"id": _new_item_id(), "label": label, "done": False} for label in DEFAULT_CHECKLIST]


def _checklist_to_db(items: list[ChecklistItem]) -> list[dict]:
    """Stored form of a validated checklist; items without an id get one."""
    return [{"id": item.id or _new_item_id(), "label": item.label, "done": item.done} for item in items]


def _aware(value: datetime) -> datetime:
    """Naive datetimes are taken as UTC (ApplicationCreate accepts either)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def recompute_interview_datetime(db: Session, application_id: int) -> None:
    """`applications.interview_datetime` = the earliest `scheduled_at` among
    the application's rounds that are still `scheduled` (null if none)."""
    db.flush()
    earliest = db.scalar(
        select(func.min(InterviewRound.scheduled_at)).where(
            InterviewRound.application_id == application_id,
            InterviewRound.state == InterviewState.SCHEDULED,
        )
    )
    application = db.get(Application, application_id)
    if application is not None and application.interview_datetime != earliest:
        application.interview_datetime = earliest


def add_round(db: Session, data: InterviewRoundCreate) -> InterviewRound:
    """`create_round` without the commit, so creating an application with an
    interview date saves the application and its first round together."""
    if db.get(Application, data.application_id) is None:
        raise ApplicationNotFoundError(data.application_id)
    fields = data.model_dump(exclude={"checklist"})
    checklist = default_checklist() if data.checklist is None else _checklist_to_db(data.checklist)
    interview_round = InterviewRound(**fields, checklist=checklist)
    db.add(interview_round)
    recompute_interview_datetime(db, data.application_id)
    return interview_round


def add_round_for_datetime(db: Session, application: Application, when: datetime) -> InterviewRound:
    """The round an interview date given at application create becomes (spec
    §4): `scheduled` if still ahead, `done` if already past, as the 0007
    data migration does for existing dates."""
    when = _aware(when)
    state = InterviewState.SCHEDULED if when >= _now() else InterviewState.DONE
    return add_round(
        db, InterviewRoundCreate(application_id=application.id, scheduled_at=when, state=state)
    )


def create_round(db: Session, data: InterviewRoundCreate) -> InterviewRound:
    interview_round = add_round(db, data)
    db.commit()
    return interview_round


def get_round(db: Session, round_id: int) -> InterviewRound:
    interview_round = db.get(InterviewRound, round_id)
    if interview_round is None:
        raise InterviewRoundNotFoundError(round_id)
    return interview_round


def _is_upcoming(now: datetime):
    return (InterviewRound.state == InterviewState.SCHEDULED) & or_(
        InterviewRound.scheduled_at.is_(None), InterviewRound.scheduled_at >= now
    )


def list_rounds(
    db: Session,
    scope: RoundScope = "all",
    application_id: int | None = None,
    now: datetime | None = None,
) -> list[InterviewRound]:
    """`upcoming`: still scheduled and not yet started (or no date yet),
    soonest first with undated rounds last. `past`: everything else, most
    recent first. `all`: by date, undated last."""
    now = now or _now()
    query = select(InterviewRound)
    if application_id is not None:
        query = query.where(InterviewRound.application_id == application_id)
    if scope == "upcoming":
        query = query.where(_is_upcoming(now))
    elif scope == "past":
        query = query.where(~_is_upcoming(now))
    if scope == "past":
        query = query.order_by(InterviewRound.scheduled_at.desc().nulls_last(), InterviewRound.id.desc())
    else:
        query = query.order_by(InterviewRound.scheduled_at.asc().nulls_last(), InterviewRound.id)
    return list(db.scalars(query))


def update_round(db: Session, round_id: int, data: InterviewRoundUpdate) -> InterviewRound:
    interview_round = get_round(db, round_id)
    fields = data.model_dump(exclude_unset=True, exclude={"checklist"})
    for name, value in fields.items():
        setattr(interview_round, name, value)
    if "checklist" in data.model_fields_set:
        interview_round.checklist = _checklist_to_db(data.checklist)
    recompute_interview_datetime(db, interview_round.application_id)
    db.commit()
    return interview_round


def delete_round(db: Session, round_id: int) -> None:
    interview_round = get_round(db, round_id)
    application_id = interview_round.application_id
    db.delete(interview_round)
    recompute_interview_datetime(db, application_id)
    db.commit()


def set_round_contacts(db: Session, round_id: int, contact_ids: list[int]) -> InterviewRound:
    """Replace the round's tracked interviewers. Each contact must belong to
    the round's application or to none; an unattached one is linked to it."""
    interview_round = get_round(db, round_id)
    contacts: list[Contact] = []
    for contact_id in dict.fromkeys(contact_ids):
        contact = db.get(Contact, contact_id)
        if contact is None:
            raise ContactNotFoundError(contact_id)
        if contact.application_id not in (None, interview_round.application_id):
            raise ContactNotOnApplicationError(
                f"contact {contact_id} belongs to another application"
            )
        contacts.append(contact)
    for contact in contacts:
        contact.application_id = interview_round.application_id
    interview_round.contacts = contacts
    db.commit()
    return interview_round


def set_round_stories(db: Session, round_id: int, story_ids: list[int]) -> InterviewRound:
    """Replace the stories planned for the round."""
    interview_round = get_round(db, round_id)
    stories: list[Story] = []
    for story_id in dict.fromkeys(story_ids):
        story = db.get(Story, story_id)
        if story is None:
            raise StoryNotFoundError(story_id)
        stories.append(story)
    interview_round.stories = stories
    db.commit()
    return interview_round


def thank_you_due(interview_round: InterviewRound, now: datetime | None = None) -> bool:
    """A done round whose thank-you is not marked sent, for 3 days after it
    was scheduled. A round with no date never comes due."""
    now = now or _now()
    return (
        interview_round.state == InterviewState.DONE
        and interview_round.thank_you_sent_at is None
        and interview_round.scheduled_at is not None
        and interview_round.scheduled_at >= now - THANK_YOU_WINDOW
    )


def checklist_progress(interview_round: InterviewRound) -> tuple[int, int]:
    """(items done, items total)."""
    items = interview_round.checklist or []
    return sum(1 for item in items if item.get("done")), len(items)
