from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.schemas.application import ApplicationCreate
from app.schemas.contact import ContactCreate
from app.services import sheets_client
from app.services.application_service import archive_application, create_application
from app.services.contact_service import apply_action, create_contact
from app.services.contact_transitions import ContactAction
from app.services.errors import GoogleAuthError, SheetSyncError
from app.services.settings_service import get_settings
from app.services.sheet_sync_service import (
    ALL_TABS,
    HEADER_NOTE,
    NEEDS_ATTENTION_HEADER,
    SHEET_TITLE,
    TAB_APPLICATIONS,
    TAB_COMPANY,
    TAB_PROFESSORS,
    safe_sync,
    sync_tabs,
)
from app.services.sheets_client import GoogleSheetsClient

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeSheetsClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created: list[tuple[str, list[str]]] = []
        self.replaced: dict[str, list[list[str]]] = {}

    def create_spreadsheet(self, title, tab_titles):
        self.created.append((title, list(tab_titles)))
        return f"sheet-{len(self.created)}"

    def replace_tab(self, spreadsheet_id, tab, rows):
        if self.fail:
            raise SheetSyncError("sheets update rejected (status 500)")
        self.replaced[tab] = rows


def test_first_sync_creates_sheet_and_stores_id(db_session):
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, ALL_TABS)
    assert fake.created == [(SHEET_TITLE, list(ALL_TABS))]
    assert get_settings(db_session).backup_sheet_id == "sheet-1"
    assert set(fake.replaced) == set(ALL_TABS)


def test_first_sync_fills_every_tab_even_when_one_changed(db_session):
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_PROFESSORS])
    assert set(fake.replaced) == set(ALL_TABS)
    fake.replaced.clear()
    sync_tabs(db_session, fake, [TAB_PROFESSORS])
    assert set(fake.replaced) == {TAB_PROFESSORS}


def test_second_sync_reuses_sheet(db_session):
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_APPLICATIONS])
    sync_tabs(db_session, fake, [TAB_APPLICATIONS])
    assert len(fake.created) == 1


def test_application_rows_include_archived_with_flag(db_session):
    a = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE"))
    b = create_application(db_session, ApplicationCreate(company="Acme", role_title="=HYPERLINK(\"x\")"))
    archive_application(db_session, b.id)
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_APPLICATIONS])
    rows = fake.replaced[TAB_APPLICATIONS]
    assert rows[0] == [HEADER_NOTE] and rows[1][0] == "id"
    archived_col = rows[1].index("archived")
    by_id = {r[0]: r for r in rows[2:]}
    assert by_id[str(a.id)][archived_col] == "FALSE" and by_id[str(b.id)][archived_col] == "TRUE"
    assert all(isinstance(v, str) for r in rows for v in r)


def test_contact_tabs_split_by_kind_with_header_note(db_session):
    create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    create_contact(db_session, ContactCreate(kind="company", name="Sam", organization="Stripe"))
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_PROFESSORS, TAB_COMPANY])
    for tab, name in [(TAB_PROFESSORS, "Jane"), (TAB_COMPANY, "Sam")]:
        rows = fake.replaced[tab]
        assert rows[0] == [HEADER_NOTE] and len(rows) == 3
        assert rows[2][rows[1].index("name")] == name
        for col in ("status", "email", "email_confidence", "sent_at", "draft_subject", "draft_body", NEEDS_ATTENTION_HEADER):
            assert col in rows[1]


def test_needs_attention_column_filled(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    now = datetime.now(UTC)
    apply_action(db_session, c.id, ContactAction.SENT, on=now - timedelta(days=12), now=now)
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_PROFESSORS])
    rows = fake.replaced[TAB_PROFESSORS]
    assert rows[2][rows[1].index(NEEDS_ATTENTION_HEADER)] == "followup_due"
    assert rows[2][rows[1].index("sent_at")].startswith((now - timedelta(days=12)).date().isoformat())


def test_safe_sync_success_records_time_and_clears_error(db_session):
    s = get_settings(db_session)
    s.last_sheet_sync_error = "old error"
    db_session.flush()
    assert safe_sync(db_session, lambda db: FakeSheetsClient(), ALL_TABS, now=NOW) is True
    assert s.last_sheet_sync_at == NOW and s.last_sheet_sync_error is None


def test_safe_sync_records_error_and_returns_false(db_session):
    assert safe_sync(db_session, lambda db: FakeSheetsClient(fail=True), ALL_TABS, now=NOW) is False
    s = get_settings(db_session)
    assert s.last_sheet_sync_error == "sheet sync failed: sheets update rejected (status 500)"
    assert s.last_sheet_sync_at is None
    assert s.backup_sheet_id == "sheet-1"  # kept, so the next sync reuses it


def test_safe_sync_handles_google_not_connected(db_session):
    def factory(db):
        raise GoogleAuthError("google is not connected")

    assert safe_sync(db_session, factory, ALL_TABS) is False
    assert get_settings(db_session).last_sheet_sync_error == "google not connected"


def test_safe_sync_truncates_long_errors(db_session):
    def factory(db):
        raise RuntimeError("x" * 1000)

    safe_sync(db_session, factory, ALL_TABS)
    assert get_settings(db_session).last_sheet_sync_error == "sheet sync failed: " + "x" * 300


def test_google_client_raw_writes_and_error_mapping(monkeypatch):
    calls = []

    def fake_request(method, url, headers, timeout, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/spreadsheets"):
            return httpx.Response(200, json={"spreadsheetId": "abc"})
        return httpx.Response(200, json={})

    monkeypatch.setattr(sheets_client.httpx, "request", fake_request)
    client = GoogleSheetsClient("tok")
    assert client.create_spreadsheet("T", ["Applications"]) == "abc"
    client.replace_tab("abc", "Company Contacts", [["a"]])
    _, clear_url, _ = calls[1]
    method, put_url, kwargs = calls[2]
    assert clear_url.endswith("/abc/values/%27Company%20Contacts%27:clear")
    assert method == "PUT" and kwargs["params"] == {"valueInputOption": "RAW"} and kwargs["json"] == {"values": [["a"]]}

    monkeypatch.setattr(sheets_client.httpx, "request", lambda *a, **k: httpx.Response(403, text="secret body"))
    with pytest.raises(SheetSyncError) as exc:
        client.replace_tab("abc", "Applications", [])
    assert "403" in str(exc.value) and "secret" not in str(exc.value)
    assert "reconnect Google" in str(exc.value)

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(sheets_client.httpx, "request", boom)
    with pytest.raises(SheetSyncError):
        client.create_spreadsheet("T", [])
