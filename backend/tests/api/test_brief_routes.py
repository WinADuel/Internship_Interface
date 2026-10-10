"""The company brief (Phase 4 spec §4): the user's two cookie routes, and the
Claude job's /work entry and POST /api/claude/briefs."""

import pytest

from app.models.application import Application
from app.models.contact import Contact
from app.models.prep_brief import PrepBrief
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.services.claude_token_service import create_token

ROUTES = [
    ("GET", "/api/applications/1/brief"),
    ("POST", "/api/applications/1/brief/request"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_a_session(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401 and r.json() == {"detail": "not authenticated"}


def _app(client, **fields) -> dict:
    body = {"company": "Acme", "role_title": "SWE Intern", "job_link": "https://acme.com/jobs/1", **fields}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(db_session) -> dict:
    _, raw = create_token(db_session)
    return {"Authorization": f"Bearer {raw}"}


def test_request_brief_then_409_while_pending(logged_in_client, sheet_sync_recorder):
    a = _app(logged_in_client)
    sheet_sync_recorder.scheduled.clear()
    r = logged_in_client.post(f"/api/applications/{a['id']}/brief/request")
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "interview_brief" and body["state"] == "pending"
    assert body["application_id"] == a["id"] and body["target_count"] == 1
    assert body["request_text"] == "Acme — SWE Intern — https://acme.com/jobs/1"
    r = logged_in_client.post(f"/api/applications/{a['id']}/brief/request")
    assert r.status_code == 409 and r.json() == {"detail": "brief already requested"}
    pending = logged_in_client.get("/api/research-queue", params={"state": "pending"}).json()
    assert [i["kind"] for i in pending] == ["interview_brief"]
    assert sheet_sync_recorder.scheduled == []


def test_brief_routes_unknown_application_404(logged_in_client):
    for method, path in [("GET", "/api/applications/999999/brief"), ("POST", "/api/applications/999999/brief/request")]:
        r = logged_in_client.request(method, path)
        assert r.status_code == 404 and r.json() == {"detail": "application not found"}


def test_get_brief_404_until_one_exists(logged_in_client, db_session):
    a = _app(logged_in_client)
    r = logged_in_client.get(f"/api/applications/{a['id']}/brief")
    assert r.status_code == 404 and r.json() == {"detail": "brief not found"}
    db_session.add(PrepBrief(application_id=a["id"], body="Acme makes anvils.", sources=[]))
    db_session.flush()
    body = logged_in_client.get(f"/api/applications/{a['id']}/brief").json()
    assert set(body) == {"id", "application_id", "body", "sources", "created_at", "updated_at"}
    assert body["body"] == "Acme makes anvils." and body["sources"] == []


def test_full_flow_request_work_deliver_read(logged_in_client, db_session):
    a = _app(logged_in_client, notes="private: salary talk", contact_person="Secret Person")
    item_id = logged_in_client.post(f"/api/applications/{a['id']}/brief/request").json()["id"]
    cookies = dict(logged_in_client.cookies)
    logged_in_client.cookies.clear()
    headers = _bearer(db_session)

    work = logged_in_client.get("/api/claude/work", headers=headers).json()
    assert work["queue"] == [
        {"id": item_id, "kind": "interview_brief", "request_text": "Acme — SWE Intern — https://acme.com/jobs/1", "target_count": 1}
    ]
    assert "private" not in str(work["queue"]) and "Secret" not in str(work["queue"])

    r = logged_in_client.post(
        "/api/claude/briefs",
        headers=headers,
        json={
            "queue_item_id": item_id,
            "body": "  Acme makes anvils.\x00\nLikely topics: ...  ",
            "sources": [
                {"label": "About", "url": "https://acme.com/about"},
                {"label": "Bad", "url": "javascript:alert(1)"},
                {"label": "Relative", "url": "/news"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "Acme makes anvils.\nLikely topics: ..."
    assert r.json()["sources"] == [{"label": "About", "url": "https://acme.com/about"}]
    item = db_session.get(ResearchQueueItem, item_id)
    assert item.state == QueueState.DONE and item.result_note == "brief saved" and item.completed_at
    assert logged_in_client.get("/api/claude/work", headers=headers).json()["queue"] == []

    logged_in_client.cookies.update(cookies)
    assert logged_in_client.get(f"/api/applications/{a['id']}/brief").json()["body"].startswith("Acme")
    # A new request after the last is done, and its delivery replaces the brief.
    new_id = logged_in_client.post(f"/api/applications/{a['id']}/brief/request").json()["id"]
    logged_in_client.cookies.clear()
    r = logged_in_client.post("/api/claude/briefs", headers=headers, json={"queue_item_id": new_id, "body": "v2"})
    assert r.status_code == 200 and r.json()["sources"] == []
    assert db_session.query(PrepBrief).filter_by(application_id=a["id"]).count() == 1
    assert db_session.query(PrepBrief).filter_by(application_id=a["id"]).one().body == "v2"


def _brief_item(db_session, application_id=None, kind=QueueKind.INTERVIEW_BRIEF, state=QueueState.PENDING):
    if application_id is None:
        application = Application(company="Acme", role_title="SWE")
        db_session.add(application)
        db_session.flush()
        application_id = application.id
    item = ResearchQueueItem(kind=kind, request_text="Acme — SWE", application_id=application_id, state=state)
    db_session.add(item)
    db_session.flush()
    return item


def test_brief_ingest_errors(client, db_session):
    headers = _bearer(db_session)
    post = lambda body: client.post("/api/claude/briefs", headers=headers, json=body)  # noqa: E731

    r = post({"queue_item_id": 999_999, "body": "x"})
    assert r.status_code == 404 and r.json() == {"detail": "queue item not found"}
    done = _brief_item(db_session, state=QueueState.DONE)
    r = post({"queue_item_id": done.id, "body": "x"})
    assert r.status_code == 409 and r.json() == {"detail": "queue item not pending"}
    contacts_item = _brief_item(db_session, kind=QueueKind.COMPANY_CONTACTS)
    r = post({"queue_item_id": contacts_item.id, "body": "x"})
    assert r.status_code == 409 and r.json() == {"detail": "queue item is not an interview brief"}
    assert db_session.get(ResearchQueueItem, contacts_item.id).state == QueueState.PENDING

    item = _brief_item(db_session)
    for bad in (
        {"body": ""},
        {"body": "   "},
        {"body": "x" * 12_001},
        {"body": "x", "sources": [{"label": "a", "url": "https://a.b"}] * 21},
        {"body": "x", "sources": [{"label": "a" * 201, "url": "https://a.b"}]},
        {"body": "x", "sources": [{"label": "a", "url": "https://a.b/" + "x" * 2000}]},
    ):
        assert post({"queue_item_id": item.id, **bad}).status_code == 422, bad
    assert post({"queue_item_id": item.id, "body": "x" * 12_000}).status_code == 200
    assert db_session.query(PrepBrief).count() == 1


def test_brief_for_deleted_application_fails_the_item(client, db_session):
    headers = _bearer(db_session)
    item = _brief_item(db_session)
    db_session.delete(db_session.get(Application, item.application_id))
    db_session.flush()
    db_session.refresh(item)
    r = client.post("/api/claude/briefs", headers=headers, json={"queue_item_id": item.id, "body": "x"})
    assert r.status_code == 409 and r.json() == {"detail": "application no longer exists"}
    assert item.state == QueueState.FAILED and db_session.query(PrepBrief).count() == 0


def test_contact_ingest_refuses_brief_items(client, db_session):
    headers = _bearer(db_session)
    item = _brief_item(db_session)
    r = client.post(
        "/api/claude/contacts",
        headers=headers,
        json={"contacts": [{"queue_item_id": item.id, "name": "P", "organization": "Acme", "email_confidence": "not_found"}]},
    )
    assert r.status_code == 200 and r.json() == {"created": 0, "updated": 0, "skipped": 1}
    assert db_session.query(Contact).count() == 0
    assert db_session.get(ResearchQueueItem, item.id).state == QueueState.PENDING


def test_brief_ingest_requires_the_claude_token(logged_in_client, db_session):
    item = _brief_item(db_session)
    r = logged_in_client.post("/api/claude/briefs", json={"queue_item_id": item.id, "body": "x"})
    assert r.status_code == 401 and r.json() == {"detail": "invalid claude token"}
