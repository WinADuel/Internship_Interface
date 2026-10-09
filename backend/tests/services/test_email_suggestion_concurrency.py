"""Two decisions on one email suggestion at once (Phase 6 review): the row
lock makes the second wait for the first and then see it decided, so an
interview round is never added twice.

Each race needs two real transactions, so these tests commit through their
own sessions and delete what they made afterwards."""

import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.models.interview import InterviewRound
from app.models.research_queue import ResearchQueueItem
from app.models.status_history import StatusHistory
from app.services import email_suggestion_service as service
from app.services.errors import SuggestionNotPendingError

COMPANY = "Racecond Email"
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


@pytest.fixture()
def committed_suggestion(_engine):
    with Session(_engine) as s:
        application = Application(company=COMPANY, role_title="Concurrency Intern", status=ApplicationStatus.APPLIED)
        s.add(application)
        s.flush()
        suggestion = EmailSuggestion(
            gmail_message_id="race-accept-1",
            gmail_thread_id="race-thread-1",
            received_at=NOW,
            direction=EmailDirection.INBOUND,
            from_name="Racecond",
            from_email="jobs@racecond.com",
            subject="Interview invitation",
            snippet="",
            kind=SuggestionKind.INTERVIEW,
            application_id=application.id,
        )
        s.add(suggestion)
        s.commit()
        ids = (suggestion.id, application.id)
    yield ids
    with Session(_engine) as s:
        suggestion_id, app_id = ids
        s.execute(delete(EmailSuggestion).where(EmailSuggestion.id == suggestion_id))
        s.execute(delete(ResearchQueueItem).where(ResearchQueueItem.application_id == app_id))
        s.execute(delete(InterviewRound).where(InterviewRound.application_id == app_id))
        s.execute(delete(StatusHistory).where(StatusHistory.application_id == app_id))
        s.execute(delete(Application).where(Application.id == app_id))
        s.commit()


def _race(_engine, monkeypatch, first_call, second_call) -> list[object]:
    """Runs the two calls in two sessions at once. The first pauses inside
    `is_valid` (past the pending check) until the second is waiting on a
    lock, or 2 s pass when nothing makes it wait."""
    release = threading.Event()
    first_inside = threading.Event()
    real = service.is_valid

    def pausing(db, suggestion):
        result = real(db, suggestion)
        if not first_inside.is_set():
            first_inside.set()
            release.wait(10)
        return result

    monkeypatch.setattr(service, "is_valid", pausing)
    outcomes: dict[int, object] = {}

    def run(slot: int, call) -> None:
        with Session(_engine) as s:
            try:
                outcomes[slot] = call(s)
            except Exception as exc:  # noqa: BLE001 - the test inspects it
                s.rollback()
                outcomes[slot] = exc

    first = threading.Thread(target=run, args=(0, first_call))
    first.start()
    assert first_inside.wait(10)
    second = threading.Thread(target=run, args=(1, second_call))
    second.start()
    with _engine.connect() as watcher:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            waiting = watcher.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            ).scalar_one()
            watcher.rollback()
            if waiting:
                break
            time.sleep(0.02)
    release.set()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    return [outcomes[0], outcomes[1]]


def test_a_double_accept_applies_once(_engine, committed_suggestion, monkeypatch):
    suggestion_id, app_id = committed_suggestion

    def accept(s: Session):
        return service.accept(s, suggestion_id, now=NOW).suggestion.state

    outcomes = _race(_engine, monkeypatch, accept, accept)

    assert outcomes[0] == SuggestionState.ACCEPTED
    assert isinstance(outcomes[1], SuggestionNotPendingError), outcomes
    with Session(_engine) as s:
        rounds = s.scalars(select(InterviewRound).where(InterviewRound.application_id == app_id)).all()
        assert len(rounds) == 1


def test_a_dismiss_during_an_accept_waits_and_is_refused(_engine, committed_suggestion, monkeypatch):
    suggestion_id, _ = committed_suggestion

    outcomes = _race(
        _engine,
        monkeypatch,
        lambda s: service.accept(s, suggestion_id, now=NOW).suggestion.state,
        lambda s: service.dismiss(s, suggestion_id, now=NOW).state,
    )

    assert outcomes[0] == SuggestionState.ACCEPTED
    assert isinstance(outcomes[1], SuggestionNotPendingError), outcomes
    with Session(_engine) as s:
        assert s.get(EmailSuggestion, suggestion_id).state == SuggestionState.ACCEPTED
