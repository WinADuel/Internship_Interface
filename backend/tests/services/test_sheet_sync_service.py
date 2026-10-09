from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app.models.posting import Posting, PostingSource, PostingState
from app.schemas.application import ApplicationCreate
from app.schemas.contact import ContactCreate
from app.schemas.interview import InterviewRoundCreate
from app.services import sheets_client
from app.services.application_service import archive_application, create_application
from app.services.contact_service import apply_action, create_contact
from app.services.contact_transitions import ContactAction
from app.services.errors import GoogleAuthError, SheetSyncError
from app.services.interview_service import create_round
from app.services.settings_service import get_settings
from app.services.sheet_sync_service import (
    ALL_TABS,
    HEADER_NOTE,
    NEEDS_ATTENTION_HEADER,
    SHEET_TITLE,
    TAB_APPLICATIONS,
    TAB_COMPANY,
    TAB_INTERVIEWS,
    TAB_PROFESSORS,
    TAB_SAVED_POSTINGS,
    safe_sync,
    sync_tabs,
)
from app.services.discovery.urls import normalize_url
from app.services.sheets_client import GoogleSheetsClient

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeSheetsClient:
    """In-memory Sheets: like the real API, writing a tab the sheet lacks fails."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created: list[tuple[str, list[str]]] = []
        self.sheets: dict[str, list[str]] = {}
        self.ensure_calls: list[tuple[str, list[str]]] = []
        self.added: list[str] = []
        self.replaced: dict[str, list[list[str]]] = {}

    def create_spreadsheet(self, title, tab_titles):
        self.created.append((title, list(tab_titles)))
        sheet_id = f"sheet-{len(self.created)}"
        self.sheets[sheet_id] = list(tab_titles)
        return sheet_id

    def ensure_tabs(self, spreadsheet_id, titles):
        self.ensure_calls.append((spreadsheet_id, list(titles)))
        tabs = self.sheets[spreadsheet_id]
        for title in titles:
            if title not in tabs:
                tabs.append(title)
                self.added.append(title)

    def replace_tab(self, spreadsheet_id, tab, rows):
        if self.fail:
            raise SheetSyncError("sheets update rejected (status 500)")
        if tab not in self.sheets.get(spreadsheet_id, []):
            raise SheetSyncError("sheets clear rejected (status 400)")
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


def test_all_tabs_include_saved_postings_and_interviews():
    assert ALL_TABS == (TAB_APPLICATIONS, TAB_PROFESSORS, TAB_COMPANY, TAB_SAVED_POSTINGS, TAB_INTERVIEWS)


def test_new_sheet_is_created_with_every_tab_and_needs_no_ensure(db_session):
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_SAVED_POSTINGS])
    assert fake.created == [(SHEET_TITLE, list(ALL_TABS))]
    assert fake.ensure_calls == [] and set(fake.replaced) == set(ALL_TABS)


def test_old_three_tab_sheet_gains_saved_postings_tab_once(db_session):
    get_settings(db_session).backup_sheet_id = "old"
    db_session.flush()
    fake = FakeSheetsClient()
    fake.sheets["old"] = [TAB_APPLICATIONS, TAB_PROFESSORS, TAB_COMPANY]
    sync_tabs(db_session, fake, ALL_TABS)
    assert fake.created == []
    assert fake.ensure_calls == [("old", list(ALL_TABS))]
    assert fake.added == [TAB_SAVED_POSTINGS, TAB_INTERVIEWS]
    assert set(fake.replaced) == set(ALL_TABS)
    fake.replaced.clear()
    sync_tabs(db_session, fake, [TAB_SAVED_POSTINGS, TAB_SAVED_POSTINGS])
    assert fake.ensure_calls[-1] == ("old", [TAB_SAVED_POSTINGS])
    assert fake.added == [TAB_SAVED_POSTINGS, TAB_INTERVIEWS]  # not added a second time
    assert set(fake.replaced) == {TAB_SAVED_POSTINGS}


def test_unknown_tab_is_refused_before_touching_the_sheet(db_session):
    get_settings(db_session).backup_sheet_id = "old"
    db_session.flush()
    fake = FakeSheetsClient()
    fake.sheets["old"] = list(ALL_TABS)
    with pytest.raises(ValueError):
        sync_tabs(db_session, fake, [TAB_APPLICATIONS, "Bogus"])
    assert fake.ensure_calls == [] and fake.replaced == {}


def _posting(db, key, *, state, title="Software Intern", company="Acme", locations=None,
             closed=False, changed=NOW):
    url = f"https://jobs.example.com/{key}"
    p = Posting(
        source=PostingSource.SIMPLIFY, source_key=key, company=company, title=title,
        locations=locations if locations is not None else [], url=url, url_key=normalize_url(url),
        state=state, state_changed_at=changed, closed=closed,
    )
    db.add(p)
    db.flush()
    return p


def test_saved_posting_rows(db_session):
    _posting(db_session, "old", state=PostingState.SAVED, company="Beta", title="Data Intern",
             changed=NOW - timedelta(days=3), closed=True)
    _posting(db_session, "new", state=PostingState.SAVED, title='=HYPERLINK("http://x","y")',
             locations=["New York, NY", "Remote"], changed=NOW - timedelta(hours=1))
    for state in (PostingState.NEW, PostingState.DISMISSED, PostingState.APPLIED):
        _posting(db_session, f"other-{state.value}", state=state)
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_SAVED_POSTINGS])
    rows = fake.replaced[TAB_SAVED_POSTINGS]
    assert rows[0] == [HEADER_NOTE]
    assert rows[1] == ["Company", "Role", "Locations", "Link", "Saved", "Closed"]
    assert rows[2:] == [
        ["Acme", '=HYPERLINK("http://x","y")', "New York, NY; Remote", "https://jobs.example.com/new",
         "2026-10-06", ""],
        ["Beta", "Data Intern", "", "https://jobs.example.com/old", "2026-10-03", "yes"],
    ]
    assert all(isinstance(v, str) for r in rows for v in r)


def test_four_tab_sheet_gains_interviews_tab(db_session):
    get_settings(db_session).backup_sheet_id = "old"
    db_session.flush()
    fake = FakeSheetsClient()
    fake.sheets["old"] = [TAB_APPLICATIONS, TAB_PROFESSORS, TAB_COMPANY, TAB_SAVED_POSTINGS]
    sync_tabs(db_session, fake, [TAB_APPLICATIONS, TAB_INTERVIEWS])
    assert fake.added == [TAB_INTERVIEWS]
    assert set(fake.replaced) == {TAB_APPLICATIONS, TAB_INTERVIEWS}


def test_interview_rows(db_session):
    acme = create_application(db_session, ApplicationCreate(company="Acme", role_title="SWE Intern"))
    beta = create_application(db_session, ApplicationCreate(company="Beta", role_title='=HYPERLINK("x")'))
    archive_application(db_session, beta.id)
    pacific = timezone(timedelta(hours=-7))
    create_round(
        db_session,
        InterviewRoundCreate(
            application_id=acme.id,
            kind="technical",
            scheduled_at=datetime(2026, 10, 20, 9, 0, tzinfo=pacific),
            prep_notes="PRIVATE NOTES",
            questions_to_ask="PRIVATE QUESTIONS",
        ),
    )
    create_round(
        db_session,
        InterviewRoundCreate(
            application_id=beta.id,
            title="Final loop",
            scheduled_at=NOW,
            state="done",
            outcome="passed",
            thank_you_sent_at=NOW + timedelta(hours=20),
            reflection="PRIVATE REFLECTION",
        ),
    )
    create_round(db_session, InterviewRoundCreate(application_id=acme.id))
    fake = FakeSheetsClient()
    sync_tabs(db_session, fake, [TAB_INTERVIEWS])
    rows = fake.replaced[TAB_INTERVIEWS]
    assert rows[0] == [HEADER_NOTE]
    assert rows[1] == ["Company", "Role", "Round", "Scheduled", "State", "Outcome", "Thank-you sent"]
    assert rows[2:] == [
        ["Beta", '=HYPERLINK("x")', "Final loop", "2026-10-06T12:00:00+00:00", "done", "passed",
         "2026-10-07T08:00:00+00:00"],
        ["Acme", "SWE Intern", "Technical", "2026-10-20T16:00:00+00:00", "scheduled", "", ""],
        ["Acme", "SWE Intern", "Interview", "", "scheduled", "", ""],
    ]
    assert "PRIVATE" not in str(rows)
    assert all(isinstance(v, str) for r in rows for v in r)


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


def test_google_client_ensure_tabs_adds_only_missing(monkeypatch):
    calls = []
    existing = {"sheets": [{"properties": {"title": "Applications"}}, {"properties": {"title": "Professors"}}]}

    def fake_request(method, url, headers, timeout, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json=existing if method == "GET" else {})

    monkeypatch.setattr(sheets_client.httpx, "request", fake_request)
    client = GoogleSheetsClient("tok")
    client.ensure_tabs("a/b", ["Applications", "Professors", "Saved postings", "Company Contacts"])
    (get_method, get_url, get_kwargs), (post_method, post_url, post_kwargs) = calls
    assert get_method == "GET" and get_url == f"{sheets_client.SHEETS_API}/a%2Fb"
    assert get_kwargs["params"] == {"fields": "sheets.properties.title"}
    assert post_method == "POST" and post_url == f"{sheets_client.SHEETS_API}/a%2Fb:batchUpdate"
    assert post_kwargs["json"] == {
        "requests": [
            {"addSheet": {"properties": {"title": "Saved postings"}}},
            {"addSheet": {"properties": {"title": "Company Contacts"}}},
        ]
    }

    calls.clear()
    client.ensure_tabs("abc", ["Applications"])
    assert [c[0] for c in calls] == ["GET"]  # nothing missing: no batchUpdate


def test_google_client_ensure_tabs_errors(monkeypatch):
    client = GoogleSheetsClient("tok")
    monkeypatch.setattr(sheets_client.httpx, "request", lambda *a, **k: httpx.Response(401, text="secret body"))
    with pytest.raises(SheetSyncError) as exc:
        client.ensure_tabs("abc", ["Saved postings"])
    assert "401" in str(exc.value) and "secret" not in str(exc.value) and "reconnect Google" in str(exc.value)

    def reject_add(method, url, headers, timeout, **kwargs):
        if method == "GET":
            return httpx.Response(200, json={"sheets": []})
        return httpx.Response(400, text="secret body")

    monkeypatch.setattr(sheets_client.httpx, "request", reject_add)
    with pytest.raises(SheetSyncError) as exc:
        client.ensure_tabs("abc", ["Saved postings"])
    assert "400" in str(exc.value) and "secret" not in str(exc.value)

    for bad in ({"sheets": "nope"}, [1], {"sheets": [{"properties": {"title": 5}}]}):
        monkeypatch.setattr(sheets_client.httpx, "request", lambda *a, _b=bad, **k: httpx.Response(200, json=_b))
        with pytest.raises(SheetSyncError):
            client.ensure_tabs("abc", ["Saved postings"])
    monkeypatch.setattr(sheets_client.httpx, "request", lambda *a, **k: httpx.Response(200, text="not json"))
    with pytest.raises(SheetSyncError):
        client.ensure_tabs("abc", ["Saved postings"])
