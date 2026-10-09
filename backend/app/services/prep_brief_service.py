"""Company briefs for interview prep (Phase 4 spec §3–§4). The daily Claude
job writes them (`claude_ingest_service.save_brief`); the user reads one
per application and asks for a new one through the research queue."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.prep_brief import PrepBrief
from app.models.research_queue import ResearchQueueItem
from app.services import research_queue_service
from app.services.errors import ApplicationNotFoundError, PrepBriefNotFoundError


def _application(db: Session, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise ApplicationNotFoundError(application_id)
    return application


def find_brief(db: Session, application_id: int) -> PrepBrief | None:
    return db.scalars(select(PrepBrief).where(PrepBrief.application_id == application_id)).first()


def get_brief(db: Session, application_id: int) -> PrepBrief:
    _application(db, application_id)
    brief = find_brief(db, application_id)
    if brief is None:
        raise PrepBriefNotFoundError(application_id)
    return brief


def request_brief(db: Session, application_id: int) -> ResearchQueueItem:
    """Queues an `interview_brief` item; AlreadyQueuedError if one is pending."""
    return research_queue_service.enqueue_interview_brief(db, _application(db, application_id))
