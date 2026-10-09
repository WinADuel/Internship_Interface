"""Concurrent interview-prep writes (Phase 4 review): round writes on one
application, brief requests and brief saves each serialize on a row lock.

Each race needs two real transactions, so these tests commit through their
own sessions and delete what they made afterwards."""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.interview import InterviewRound, InterviewState
from app.models.prep_brief import PrepBrief
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.schemas.claude import BriefIn
from app.schemas.interview import InterviewRoundUpdate
from app.services import claude_ingest_service, interview_service, prep_brief_service, research_queue_service
from app.services.errors import AlreadyQueuedError, QueueItemNotPendingError

COMPANY = "Racecond Interviews"
SOON = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)


@pytest.fixture()
def committed_app(_engine):
    with Session(_engine) as s:
        application = Application(company=COMPANY, role_title="Concurrency Intern")
        s.add(application)
        s.commit()
        app_id = application.id
    yield app_id
    with Session(_engine) as s:
        s.execute(delete(ResearchQueueItem).where(ResearchQueueItem.application_id == app_id))
        s.execute(delete(PrepBrief).where(PrepBrief.application_id == app_id))
        s.execute(delete(InterviewRound).where(InterviewRound.application_id == app_id))
        s.execute(delete(Application).where(Application.id == app_id))
        s.commit()


def _race(_engine, monkeypatch, module, name: str, call: Callable[[Session], object]) -> list[object]:
    """Runs `call` in two sessions at once. The first pauses right after
    `module.name` returns until the second is waiting on a lock (or 2 s pass,
    when nothing makes it wait), then both finish. Returns each run's result,
    or the exception it raised, first run first."""
    release = threading.Event()
    first_inside = threading.Event()
    real = getattr(module, name)

    def pausing(*args, **kwargs):
        result = real(*args, **kwargs)
        if not first_inside.is_set():
            if isinstance(args[0], Session):
                args[0].flush()
            first_inside.set()
            release.wait(10)
        return result

    monkeypatch.setattr(module, name, pausing)
    outcomes: dict[int, object] = {}

    def run(slot: int) -> None:
        with Session(_engine) as s:
            try:
                outcomes[slot] = call(s)
            except Exception as exc:  # noqa: BLE001 — the test inspects it
                s.rollback()
                outcomes[slot] = exc

    first = threading.Thread(target=run, args=(0,))
    first.start()
    assert first_inside.wait(10)
    second = threading.Thread(target=run, args=(1,))
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


def test_concurrent_round_writes_leave_the_right_interview_datetime(_engine, committed_app, monkeypatch):
    """Each write marks one of two scheduled rounds done. Without the
    application lock each sees the other's round still scheduled, and the
    later commit leaves a date although no round is scheduled any more."""
    with Session(_engine) as s:
        rounds = [
            InterviewRound(application_id=committed_app, scheduled_at=SOON + timedelta(days=i), checklist=[])
            for i in range(2)
        ]
        s.add_all(rounds)
        s.flush()
        interview_service.recompute_interview_datetime(s, committed_app)
        s.commit()
        round_ids = [r.id for r in rounds]
    turn = iter(round_ids)

    def mark_done(s: Session):
        return interview_service.update_round(s, next(turn), InterviewRoundUpdate(state=InterviewState.DONE))

    outcomes = _race(_engine, monkeypatch, interview_service, "recompute_interview_datetime", mark_done)

    assert all(isinstance(o, InterviewRound) for o in outcomes), outcomes
    with Session(_engine) as s:
        assert s.get(Application, committed_app).interview_datetime is None


def test_concurrent_brief_requests_queue_one(_engine, committed_app, monkeypatch):
    outcomes = _race(
        _engine,
        monkeypatch,
        research_queue_service,
        "application_request_text",
        lambda s: prep_brief_service.request_brief(s, committed_app).id,
    )

    assert sum(isinstance(o, int) for o in outcomes) == 1
    assert sum(isinstance(o, AlreadyQueuedError) for o in outcomes) == 1
    with Session(_engine) as s:
        pending = s.scalars(
            select(ResearchQueueItem).where(
                ResearchQueueItem.application_id == committed_app,
                ResearchQueueItem.kind == QueueKind.INTERVIEW_BRIEF,
                ResearchQueueItem.state == QueueState.PENDING,
            )
        ).all()
        assert len(pending) == 1


def test_concurrent_brief_saves_store_one_and_refuse_the_other(_engine, committed_app, monkeypatch):
    """The second save waits for the first, then finds the item done (409),
    instead of hitting the one-brief-per-application unique index (500)."""
    with Session(_engine) as s:
        item_id = prep_brief_service.request_brief(s, committed_app).id
    bodies = iter(["first brief", "second brief"])

    def save(s: Session):
        brief = claude_ingest_service.save_brief(s, BriefIn(queue_item_id=item_id, body=next(bodies)))
        return brief.body

    outcomes = _race(_engine, monkeypatch, prep_brief_service, "find_brief", save)

    assert outcomes[0] == "first brief"
    assert isinstance(outcomes[1], QueueItemNotPendingError), outcomes
    with Session(_engine) as s:
        assert [b.body for b in s.scalars(select(PrepBrief).where(PrepBrief.application_id == committed_app))] == [
            "first brief"
        ]
        assert s.get(ResearchQueueItem, item_id).state == QueueState.DONE
