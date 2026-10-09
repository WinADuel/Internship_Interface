from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.contact import Contact, ContactKind
from app.models.story import Story

ROUTES = [
    ("GET", "/api/interviews"),
    ("POST", "/api/interviews"),
    ("GET", "/api/interviews/1"),
    ("PATCH", "/api/interviews/1"),
    ("DELETE", "/api/interviews/1"),
    ("PUT", "/api/interviews/1/contacts"),
    ("PUT", "/api/interviews/1/stories"),
    ("GET", "/api/interviews/1/calendar.ics"),
]

ROUND_TABS = ["Applications", "Interviews"]
CONTACT_TABS = ["Professors", "Company Contacts"]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


SOON = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)


def test_routes_list_is_complete():
    # The auth and Claude-token boundary tests walk ROUTES; keep it complete.
    from app.api.interviews import router

    served = {
        (method, route.path.replace("{round_id}", "1"))
        for route in router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert served == set(ROUTES)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_a_session(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401 and r.json() == {"detail": "not authenticated"}


def _app(client, **fields) -> dict:
    r = client.post("/api/applications", json={"company": "Acme", "role_title": "SWE Intern", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _round(client, application_id: int, **fields) -> dict:
    r = client.post("/api/interviews", json={"application_id": application_id, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_returns_detail_with_derived_fields(logged_in_client, sheet_sync_recorder):
    a = _app(logged_in_client)
    body = _round(logged_in_client, a["id"], kind="technical", scheduled_at=_iso(SOON), title="Coding 1")
    assert body["application_id"] == a["id"]
    assert body["company"] == "Acme" and body["role_title"] == "SWE Intern"
    assert body["kind"] == "technical" and body["state"] == "scheduled" and body["title"] == "Coding 1"
    assert body["checklist_done"] == 0 and body["checklist_total"] == 6
    assert len(body["checklist"]) == 6 and set(body["checklist"][0]) == {"id", "label", "done"}
    assert body["thank_you_due"] is False
    assert body["contacts"] == [] and body["stories"] == []
    assert body["scheduled_at"] == _iso(SOON)
    for key in ("prep_notes", "questions_to_ask", "reflection", "thank_you_sent_at", "created_at", "updated_at"):
        assert key in body
    assert logged_in_client.get(f"/api/applications/{a['id']}").json()["interview_datetime"] == _iso(SOON)
    assert sheet_sync_recorder.scheduled == [["Applications"], ROUND_TABS]  # application create, round create


def test_create_for_missing_application_is_422(logged_in_client, sheet_sync_recorder):
    r = logged_in_client.post("/api/interviews", json={"application_id": 999_999})
    assert r.status_code == 422 and r.json() == {"detail": "application not found"}
    assert sheet_sync_recorder.scheduled == []


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "x" * 201},
        {"duration_minutes": 4},
        {"duration_minutes": 601},
        {"location": "x" * 501},
        {"interviewers": "x" * 501},
        {"prep_notes": "x" * 20_001},
        {"questions_to_ask": "x" * 5_001},
        {"reflection": "x" * 20_001},
        {"checklist": [{"label": "x"}] * 31},
        {"checklist": [{"label": "x" * 201}]},
        {"kind": "lunch"},
        {"scheduled_at": "2026-10-12T10:00:00"},  # naive
    ],
)
def test_create_validation_caps(logged_in_client, fields):
    a = _app(logged_in_client)
    r = logged_in_client.post("/api/interviews", json={"application_id": a["id"], **fields})
    assert r.status_code == 422


def test_get_patch_and_delete(logged_in_client, sheet_sync_recorder):
    a = _app(logged_in_client)
    created = _round(logged_in_client, a["id"], scheduled_at=_iso(SOON))
    rid = created["id"]
    assert logged_in_client.get(f"/api/interviews/{rid}").json() == created

    checklist = [{**item, "done": True} for item in created["checklist"][:2]]
    r = logged_in_client.patch(
        f"/api/interviews/{rid}", json={"prep_notes": "Read the blog", "checklist": checklist, "state": "done"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prep_notes"] == "Read the blog" and body["state"] == "done"
    assert body["checklist_done"] == 2 and body["checklist_total"] == 2
    assert body["thank_you_due"] is True  # done, nothing sent yet
    assert logged_in_client.get(f"/api/applications/{a['id']}").json()["interview_datetime"] is None

    assert logged_in_client.patch(f"/api/interviews/{rid}", json={"state": None}).status_code == 422
    assert logged_in_client.delete(f"/api/interviews/{rid}").status_code == 204
    assert logged_in_client.get(f"/api/interviews/{rid}").status_code == 404
    assert sheet_sync_recorder.scheduled == [["Applications"]] + [ROUND_TABS] * 3


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/interviews/999999", None),
        ("PATCH", "/api/interviews/999999", {"title": "x"}),
        ("DELETE", "/api/interviews/999999", None),
        ("PUT", "/api/interviews/999999/contacts", {"contact_ids": []}),
        ("PUT", "/api/interviews/999999/stories", {"story_ids": []}),
        ("GET", "/api/interviews/999999/calendar.ics", None),
    ],
)
def test_missing_round_is_404(logged_in_client, sheet_sync_recorder, method, path, body):
    r = logged_in_client.request(method, path, json=body)
    assert r.status_code == 404 and r.json() == {"detail": "interview round not found"}
    assert sheet_sync_recorder.scheduled == []


def test_thank_you_due_in_list(logged_in_client):
    a = _app(logged_in_client)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    due = _round(logged_in_client, a["id"], scheduled_at=_iso(yesterday), state="done")
    assert due["thank_you_due"] is True
    sent = logged_in_client.patch(
        f"/api/interviews/{due['id']}", json={"thank_you_sent_at": _iso(datetime.now(timezone.utc))}
    ).json()
    assert sent["thank_you_due"] is False


def test_list_scopes_filters_and_shape(logged_in_client, db_session):
    a, b = _app(logged_in_client), _app(logged_in_client, company="Beta")
    later = _round(logged_in_client, a["id"], scheduled_at=_iso(SOON + timedelta(days=1)))
    soon = _round(logged_in_client, b["id"], scheduled_at=_iso(SOON))
    undated = _round(logged_in_client, a["id"])
    past = _round(logged_in_client, a["id"], scheduled_at=_iso(SOON - timedelta(days=10)), state="done")

    upcoming = logged_in_client.get("/api/interviews", params={"scope": "upcoming"}).json()
    assert [r["id"] for r in upcoming] == [soon["id"], later["id"], undated["id"]]
    assert upcoming[0]["company"] == "Beta"
    assert "contacts" not in upcoming[0] and "stories" not in upcoming[0]
    assert set(upcoming[0]) >= {"checklist_done", "checklist_total", "thank_you_due", "role_title", "prep_notes"}
    assert [r["id"] for r in logged_in_client.get("/api/interviews?scope=past").json()] == [past["id"]]
    assert len(logged_in_client.get("/api/interviews").json()) == 4
    by_app = logged_in_client.get("/api/interviews", params={"application_id": a["id"]}).json()
    assert {r["id"] for r in by_app} == {later["id"], undated["id"], past["id"]}
    assert logged_in_client.get("/api/interviews?scope=soon").status_code == 422

    # Archived applications drop out of the lists but keep their own list.
    logged_in_client.post(f"/api/applications/{b['id']}/archive")
    upcoming = logged_in_client.get("/api/interviews", params={"scope": "upcoming"}).json()
    assert [r["id"] for r in upcoming] == [later["id"], undated["id"]]
    by_b = logged_in_client.get("/api/interviews", params={"application_id": b["id"]}).json()
    assert [r["id"] for r in by_b] == [soon["id"]]


def test_set_contacts(logged_in_client, db_session, sheet_sync_recorder):
    a, other = _app(logged_in_client), _app(logged_in_client, company="Other")
    rid = _round(logged_in_client, a["id"])["id"]
    loose = Contact(kind=ContactKind.COMPANY, name="Pat", organization="Acme", email="pat@acme.com", title="EM")
    foreign = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Other", application_id=other["id"])
    db_session.add_all([loose, foreign])
    db_session.flush()
    sheet_sync_recorder.scheduled.clear()

    r = logged_in_client.put(f"/api/interviews/{rid}/contacts", json={"contact_ids": [loose.id]})
    assert r.status_code == 200
    assert r.json()["contacts"] == [{"id": loose.id, "name": "Pat", "email": "pat@acme.com", "title": "EM"}]
    assert loose.application_id == a["id"]
    assert sheet_sync_recorder.scheduled == [CONTACT_TABS]

    r = logged_in_client.put(f"/api/interviews/{rid}/contacts", json={"contact_ids": [foreign.id]})
    assert r.status_code == 422 and "another application" in r.json()["detail"]
    r = logged_in_client.put(f"/api/interviews/{rid}/contacts", json={"contact_ids": [999_999]})
    assert r.status_code == 422 and r.json() == {"detail": "contact 999999 not found"}
    assert logged_in_client.put(f"/api/interviews/{rid}/contacts", json={}).status_code == 422
    too_many = {"contact_ids": list(range(1, 52))}
    assert logged_in_client.put(f"/api/interviews/{rid}/contacts", json=too_many).status_code == 422
    assert logged_in_client.get(f"/api/interviews/{rid}").json()["contacts"][0]["id"] == loose.id
    assert sheet_sync_recorder.scheduled == [CONTACT_TABS]

    r = logged_in_client.put(f"/api/interviews/{rid}/contacts", json={"contact_ids": []})
    assert r.status_code == 200 and r.json()["contacts"] == []


def test_set_stories(logged_in_client, db_session, sheet_sync_recorder):
    rid = _round(logged_in_client, _app(logged_in_client)["id"])["id"]
    kept, archived = Story(title="Led a team"), Story(title="Old", archived=True)
    db_session.add_all([kept, archived])
    db_session.flush()
    sheet_sync_recorder.scheduled.clear()

    r = logged_in_client.put(f"/api/interviews/{rid}/stories", json={"story_ids": [kept.id]})
    assert r.status_code == 200 and r.json()["stories"] == [{"id": kept.id, "title": "Led a team"}]
    r = logged_in_client.put(f"/api/interviews/{rid}/stories", json={"story_ids": [kept.id, archived.id]})
    assert r.status_code == 422 and r.json() == {"detail": f"story {archived.id} is archived"}
    r = logged_in_client.put(f"/api/interviews/{rid}/stories", json={"story_ids": [999_999]})
    assert r.status_code == 422 and r.json() == {"detail": "story 999999 not found"}
    assert sheet_sync_recorder.scheduled == []


def test_calendar_export(logged_in_client):
    a = _app(logged_in_client, company="Acme, Inc.")
    start = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)
    rid = _round(
        logged_in_client,
        a["id"],
        kind="technical",
        scheduled_at=_iso(start),
        duration_minutes=45,
        location="https://meet.example.com/x;y",
        interviewers="Pat; Sam",
    )["id"]
    r = logged_in_client.get(f"/api/interviews/{rid}/calendar.ics")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/calendar; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="interview-{rid}.ics"'
    body = r.content.decode()
    unfolded = body.replace("\r\n ", "")
    lines = unfolded.split("\r\n")
    origin = settings.google_redirect_uri.split("/api/")[0]
    url = f"{origin}/#/interviews/{rid}"
    assert f"UID:interview-round-{rid}@internship-tracker" in lines
    assert "DTSTART:20261102T170000Z" in lines and "DTEND:20261102T174500Z" in lines
    assert "SUMMARY:Interview: Acme\\, Inc. — Technical" in lines
    assert "LOCATION:https://meet.example.com/x\\;y" in lines
    assert f"DESCRIPTION:Role: SWE Intern\\nInterviewers: Pat\\; Sam\\nPrep page: {url}" in lines
    assert f"URL:{url}" in lines
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_calendar_title_wins_and_unscheduled_round_is_409(logged_in_client):
    a = _app(logged_in_client)
    titled = _round(logged_in_client, a["id"], title="Coding round 2", scheduled_at=_iso(SOON))
    body = logged_in_client.get(f"/api/interviews/{titled['id']}/calendar.ics").content.decode()
    assert "SUMMARY:Interview: Acme — Coding round 2\r\n" in body
    undated = _round(logged_in_client, a["id"])
    r = logged_in_client.get(f"/api/interviews/{undated['id']}/calendar.ics")
    assert r.status_code == 409 and r.json() == {"detail": "interview round has no scheduled time"}
