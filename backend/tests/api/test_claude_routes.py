import pytest

from app.models.contact import Contact
from app.services.claude_token_service import create_token


@pytest.fixture()
def claude(client, db_session):
    _, raw = create_token(db_session)
    client.headers["Authorization"] = f"Bearer {raw}"
    return client


def _queue_prof(db_session):
    from app.schemas.research_queue import QueueItemCreate
    from app.services.research_queue_service import enqueue_professor

    return enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="Jane Lee"))


def _contact(item_id, i=0, **kw):
    return {"queue_item_id": item_id, "name": f"P{i}", "organization": "MIT", "email_confidence": "not_found", **kw}


def test_work_shape(claude):
    body = claude.get("/api/claude/work").json()
    assert set(body) == {"queue", "outreach_profile", "known_contacts", "followups_needed"}


def test_oversized_batch_is_422_and_writes_nothing(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, i) for i in range(26)]})
    assert r.status_code == 422
    assert db_session.query(Contact).count() == 0


def test_oversized_field_is_422(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, research_summary="x" * 5001)]})
    assert r.status_code == 422
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, sources=[{"label": "a", "url": "https://a.b"}] * 21)]})
    assert r.status_code == 422
    assert db_session.query(Contact).count() == 0


def test_valid_batch_upserts(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, 1), _contact(item.id, 2)]})
    assert r.status_code == 200 and r.json() == {"created": 2, "updated": 0, "skipped": 0}


def test_followups_route(claude, db_session):
    c = Contact(kind="professor", name="A", organization="X", status="sent")
    db_session.add(c)
    db_session.flush()
    r = claude.post(
        "/api/claude/followups",
        json={"followups": [{"contact_id": c.id, "followup_subject": "Re", "followup_body": "Hi again"}]},
    )
    assert r.status_code == 200 and r.json() == {"created": 0, "updated": 1, "skipped": 0}


def test_complete_then_complete_again_409(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post(f"/api/claude/queue/{item.id}/complete", json={"result_note": "found 1 of 1"})
    assert r.status_code == 200 and r.json()["state"] == "done" and r.json()["result_note"] == "found 1 of 1"
    r = claude.post(f"/api/claude/queue/{item.id}/complete", json={"result_note": "again"})
    assert r.status_code == 409 and r.json() == {"detail": "queue item not pending"}
    r = claude.post("/api/claude/queue/999999/failed", json={"result_note": "x"})
    assert r.status_code == 404 and r.json() == {"detail": "queue item not found"}


def test_failed_route(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post(f"/api/claude/queue/{item.id}/failed", json={"result_note": "could not identify"})
    assert r.status_code == 200 and r.json()["state"] == "failed"
