from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.application import ApplicationStatus
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.schemas.application import ApplicationCreate
from app.schemas.research_queue import QueueItemCreate
from app.services.application_service import change_status, create_application
from app.services.errors import AlreadyQueuedError, QueueItemNotFoundError, QueueItemNotPendingError
from app.services.research_queue_service import (
    complete_item,
    enqueue_company_contacts,
    enqueue_professor,
    fail_item,
    list_queue,
    pending_items,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _stripe(db, **kw):
    return create_application(
        db, ApplicationCreate(company="Stripe", role_title="SWE Intern", job_link="https://stripe.com/jobs/1", **kw)
    )


def test_marking_applied_enqueues_company_contacts_once(db_session):
    app = _stripe(db_session)
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    change_status(db_session, app.id, ApplicationStatus.INTERVIEW)
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    [item] = list_queue(db_session)
    assert item.kind == QueueKind.COMPANY_CONTACTS and item.application_id == app.id and item.target_count == 3
    assert item.request_text == "Stripe — SWE Intern — https://stripe.com/jobs/1"


def test_creating_application_as_applied_enqueues_once(db_session):
    app = _stripe(db_session, status=ApplicationStatus.APPLIED)
    change_status(db_session, app.id, ApplicationStatus.INTERVIEW)
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    [item] = list_queue(db_session)
    assert item.application_id == app.id


def test_request_text_without_job_link(db_session):
    app = create_application(db_session, ApplicationCreate(company="Acme", role_title="Intern"))
    item = enqueue_company_contacts(db_session, app)
    assert item.request_text == "Acme — Intern"


def test_manual_find_contacts_after_auto_enqueue_raises(db_session):
    app = _stripe(db_session)
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    with pytest.raises(AlreadyQueuedError):
        enqueue_company_contacts(db_session, app)
    assert len(list_queue(db_session)) == 1


def test_already_queued_counts_items_in_any_state(db_session):
    app = _stripe(db_session)
    item = enqueue_company_contacts(db_session, app)
    complete_item(db_session, item.id, "found 3 of 3", now=NOW)
    with pytest.raises(AlreadyQueuedError):
        enqueue_company_contacts(db_session, app)


def test_non_applied_status_does_not_enqueue(db_session):
    app = _stripe(db_session)
    change_status(db_session, app.id, ApplicationStatus.INTERVIEW)
    assert list_queue(db_session) == []


def test_professor_person_target_count_forced_to_one(db_session):
    item = enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="Jane Lee, Stanford", target_count=5))
    assert item.target_count == 1 and item.state == QueueState.PENDING
    search = enqueue_professor(db_session, QueueItemCreate(kind="professor_search", request_text="ML profs at UIUC", target_count=5))
    assert search.target_count == 5


def test_queue_item_create_validation():
    for bad in [
        {"kind": "company_contacts", "request_text": "x"},
        {"kind": "professor_person", "request_text": "   "},
        {"kind": "professor_person", "request_text": "x" * 1001},
        {"kind": "professor_search", "request_text": "x", "target_count": 11},
        {"kind": "professor_search", "request_text": "x", "target_count": 0},
    ]:
        with pytest.raises(ValidationError):
            QueueItemCreate(**bad)


def test_pending_items_oldest_first_and_limited(db_session):
    items = []
    for i in range(3):
        item = ResearchQueueItem(kind=QueueKind.PROFESSOR_PERSON, request_text=f"p{i}", created_at=NOW + timedelta(minutes=i))
        db_session.add(item)
        items.append(item)
    db_session.flush()
    complete_item(db_session, items[0].id, "done", now=NOW)
    assert [i.id for i in pending_items(db_session, limit=1)] == [items[1].id]
    assert [i.id for i in pending_items(db_session, limit=10)] == [items[1].id, items[2].id]
    assert [i.id for i in list_queue(db_session)] == [items[2].id, items[1].id, items[0].id]
    assert [i.id for i in list_queue(db_session, state=QueueState.DONE)] == [items[0].id]


def test_complete_and_fail_set_state_note_and_time(db_session):
    a = enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="A"))
    b = enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="B"))
    complete_item(db_session, a.id, "found 1 of 1", now=NOW)
    fail_item(db_session, b.id, "could not identify", now=NOW)
    assert (a.state, a.result_note, a.completed_at) == (QueueState.DONE, "found 1 of 1", NOW)
    assert (b.state, b.result_note) == (QueueState.FAILED, "could not identify")


def test_complete_non_pending_item_raises(db_session):
    item = enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="A"))
    complete_item(db_session, item.id, "ok", now=NOW)
    with pytest.raises(QueueItemNotPendingError):
        complete_item(db_session, item.id, "again", now=NOW)
    with pytest.raises(QueueItemNotPendingError):
        fail_item(db_session, item.id, "again", now=NOW)
    with pytest.raises(QueueItemNotFoundError):
        complete_item(db_session, 999999, "x", now=NOW)
