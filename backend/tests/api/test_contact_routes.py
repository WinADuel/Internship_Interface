from datetime import UTC, datetime, timedelta

import pytest

from app.models.contact_status_history import ContactStatusHistory


def _create(client, **overrides):
    body = {"kind": "professor", "name": "Jane Lee", "organization": "Stanford", **overrides}
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/contacts"),
        ("post", "/api/contacts"),
        ("get", "/api/contacts/activity"),
        ("get", "/api/contacts/needs-attention"),
        ("get", "/api/contacts/1"),
        ("patch", "/api/contacts/1"),
        ("post", "/api/contacts/1/actions"),
        ("post", "/api/contacts/1/status"),
        ("post", "/api/contacts/1/undo"),
        ("post", "/api/contacts/1/snooze"),
        ("post", "/api/contacts/1/archive"),
        ("get", "/api/contacts/1/history"),
        ("get", "/api/research-queue"),
        ("post", "/api/research-queue"),
        ("post", "/api/research-queue/find-contacts/1"),
        ("get", "/api/settings"),
        ("patch", "/api/settings"),
    ],
)
def test_all_routes_require_auth(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_create_action_history_round_trip(logged_in_client):
    c = _create(logged_in_client)
    assert c["status"] == "to_contact" and c["origin"] == "manual" and c["nudge"] is None
    r = logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "sent"})
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["sent_at"] is not None
    history = logged_in_client.get(f"/api/contacts/{c['id']}/history").json()
    assert [(h["old_status"], h["new_status"]) for h in history] == [("to_contact", "sent")]
    activity = logged_in_client.get("/api/contacts/activity?limit=5").json()
    assert activity[0]["contact_id"] == c["id"] and activity[0]["new_status"] == "sent"


def test_backdated_action_requires_timezone(logged_in_client):
    c = _create(logged_in_client)
    r = logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "sent", "on": "2026-10-01T09:00:00"})
    assert r.status_code == 422
    r = logged_in_client.post(
        f"/api/contacts/{c['id']}/actions", json={"action": "sent", "on": "2026-10-01T09:00:00Z"}
    )
    assert r.status_code == 200 and r.json()["sent_at"].startswith("2026-10-01T09:00:00")


def test_invalid_action_returns_422_and_changes_nothing(logged_in_client):
    c = _create(logged_in_client)
    r = logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "accepted"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert logged_in_client.get(f"/api/contacts/{c['id']}").json()["status"] == "to_contact"
    assert logged_in_client.get(f"/api/contacts/{c['id']}/history").json() == []


def test_unknown_action_value_is_422(logged_in_client):
    c = _create(logged_in_client)
    assert logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "teleport"}).status_code == 422


def test_status_move_and_invalid_move(logged_in_client):
    c = _create(logged_in_client)
    bad = logged_in_client.post(f"/api/contacts/{c['id']}/status", json={"new_status": "replied"})
    assert bad.status_code == 422
    ok = logged_in_client.post(f"/api/contacts/{c['id']}/status", json={"new_status": "sent"})
    assert ok.status_code == 200 and ok.json()["status"] == "sent"


def test_undo_within_and_after_window(logged_in_client, db_session):
    c = _create(logged_in_client)
    logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "sent"})
    r = logged_in_client.post(f"/api/contacts/{c['id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "to_contact"
    logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "sent"})
    row = db_session.query(ContactStatusHistory).filter_by(contact_id=c["id"]).one()
    row.changed_at = datetime.now(UTC) - timedelta(seconds=120)
    db_session.flush()
    r = logged_in_client.post(f"/api/contacts/{c['id']}/undo")
    assert r.status_code == 409 and r.json() == {"detail": "undo window expired"}


def test_patch_snooze_archive(logged_in_client):
    c = _create(logged_in_client)
    r = logged_in_client.patch(f"/api/contacts/{c['id']}", json={"draft_body": "hello", "notes": "n"})
    assert r.status_code == 200 and r.json()["draft_edited"] is True and r.json()["notes"] == "n"
    assert logged_in_client.patch(f"/api/contacts/{c['id']}", json={"name": None}).status_code == 422
    r = logged_in_client.post(f"/api/contacts/{c['id']}/snooze", json={"days": 3})
    assert r.status_code == 200 and r.json()["nudge_snoozed_until"] is not None
    assert logged_in_client.post(f"/api/contacts/{c['id']}/snooze", json={"days": 31}).status_code == 422
    r = logged_in_client.post(f"/api/contacts/{c['id']}/archive")
    assert r.json()["archived"] is True
    assert logged_in_client.get("/api/contacts").json() == []
    assert len(logged_in_client.get("/api/contacts?include_archived=true").json()) == 1


def test_list_filters_by_kind_and_application(logged_in_client):
    app = logged_in_client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE"}).json()
    _create(logged_in_client)
    comp = _create(logged_in_client, kind="company", name="Sam", organization="Stripe", application_id=app["id"])
    assert [x["id"] for x in logged_in_client.get("/api/contacts?kind=company").json()] == [comp["id"]]
    assert [x["id"] for x in logged_in_client.get(f"/api/contacts?application_id={app['id']}").json()] == [comp["id"]]


def test_unknown_application_and_contact(logged_in_client):
    r = logged_in_client.post(
        "/api/contacts", json={"kind": "company", "name": "S", "organization": "X", "application_id": 999999}
    )
    assert r.status_code == 422 and r.json() == {"detail": "application not found"}
    r = logged_in_client.get("/api/contacts/999999")
    assert r.status_code == 404 and r.json() == {"detail": "contact not found"}


def test_needs_attention_returns_only_due_contact(logged_in_client):
    due = _create(logged_in_client, name="Due")
    fresh = _create(logged_in_client, name="Fresh")
    long_ago = (datetime.now(UTC) - timedelta(days=12)).isoformat()
    logged_in_client.post(f"/api/contacts/{due['id']}/actions", json={"action": "sent", "on": long_ago})
    logged_in_client.post(f"/api/contacts/{fresh['id']}/actions", json={"action": "sent"})
    items = logged_in_client.get("/api/contacts/needs-attention").json()
    assert [(i["id"], i["nudge"]) for i in items] == [(due["id"], "followup_due")]
    assert logged_in_client.get(f"/api/contacts/{due['id']}").json()["nudge"] == "followup_due"
