from app.main import app
from app.api.deps import get_sheet_sync_scheduler, get_sheets_client_factory
from app.services import sheet_sync_service
from app.services.claude_token_service import create_token
from app.services.errors import SheetSyncError
from app.services.research_queue_service import enqueue_professor
from app.schemas.research_queue import QueueItemCreate
from app.services.settings_service import get_settings

CONTACT_TABS = ["Professors", "Company Contacts"]


def test_application_writes_schedule_applications_tab(logged_in_client, sheet_sync_recorder):
    a = logged_in_client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE"}).json()
    logged_in_client.patch(f"/api/applications/{a['id']}", json={"notes": "x"})
    logged_in_client.post(f"/api/applications/{a['id']}/status", json={"new_status": "applied"})
    logged_in_client.post(f"/api/applications/{a['id']}/archive")
    assert sheet_sync_recorder.scheduled == [["Applications"]] * 4


def test_reads_and_failed_writes_schedule_nothing(logged_in_client, sheet_sync_recorder):
    logged_in_client.get("/api/applications")
    logged_in_client.get("/api/contacts")
    logged_in_client.post("/api/applications/999999/archive")
    logged_in_client.post("/api/contacts/999999/actions", json={"action": "sent"})
    assert sheet_sync_recorder.scheduled == []


def test_contact_writes_schedule_both_contact_tabs(logged_in_client, sheet_sync_recorder):
    c = logged_in_client.post("/api/contacts", json={"kind": "professor", "name": "J", "organization": "S"}).json()
    logged_in_client.post(f"/api/contacts/{c['id']}/actions", json={"action": "sent"})
    logged_in_client.post(f"/api/contacts/{c['id']}/undo")
    logged_in_client.post(f"/api/contacts/{c['id']}/status", json={"new_status": "sent"})
    logged_in_client.patch(f"/api/contacts/{c['id']}", json={"notes": "n"})
    logged_in_client.post(f"/api/contacts/{c['id']}/snooze", json={"days": 3})
    logged_in_client.post(f"/api/contacts/{c['id']}/archive")
    assert sheet_sync_recorder.scheduled == [CONTACT_TABS] * 7


def test_claude_upsert_schedules_both_contact_tabs(client, db_session, sheet_sync_recorder):
    _, raw = create_token(db_session)
    item = enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="J"))
    r = client.post(
        "/api/claude/contacts",
        headers={"Authorization": f"Bearer {raw}"},
        json={"contacts": [{"queue_item_id": item.id, "name": "J", "organization": "S", "email_confidence": "not_found"}]},
    )
    assert r.status_code == 200
    r = client.post("/api/claude/followups", headers={"Authorization": f"Bearer {raw}"}, json={"followups": []})
    assert r.status_code == 200
    assert sheet_sync_recorder.scheduled == [CONTACT_TABS, CONTACT_TABS]


def test_real_scheduler_without_google_still_returns_201(logged_in_client, db_session, monkeypatch):
    # The real scheduler runs after the response, in "its own" session; here
    # that session is the test session so nothing touches another database.
    monkeypatch.setattr(sheet_sync_service, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    app.dependency_overrides[get_sheet_sync_scheduler] = lambda: sheet_sync_service.SheetSyncScheduler()
    r = logged_in_client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE"})
    assert r.status_code == 201
    assert get_settings(db_session).last_sheet_sync_error == "google not connected"
    assert logged_in_client.get(f"/api/applications/{r.json()['id']}").status_code == 200


def test_sync_now_route(logged_in_client, db_session):
    class Fake:
        def create_spreadsheet(self, title, tabs):
            return "sid"

        def replace_tab(self, sid, tab, rows):
            pass

    app.dependency_overrides[get_sheets_client_factory] = lambda: (lambda db: Fake())
    try:
        r = logged_in_client.post("/api/settings/sheet-sync")
    finally:
        app.dependency_overrides.pop(get_sheets_client_factory, None)
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["last_sheet_sync_error"] is None
    assert body["sheet_url"] == "https://docs.google.com/spreadsheets/d/sid"


def test_sync_now_reports_failure(logged_in_client):
    def factory(db):
        raise SheetSyncError("sheets create rejected (status 403)")

    app.dependency_overrides[get_sheets_client_factory] = lambda: factory
    try:
        r = logged_in_client.post("/api/settings/sheet-sync")
    finally:
        app.dependency_overrides.pop(get_sheets_client_factory, None)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["sheet_url"] is None
    assert r.json()["last_sheet_sync_error"].startswith("sheet sync failed:")


def test_sync_now_requires_cookie(client):
    assert client.post("/api/settings/sheet-sync").status_code == 401
