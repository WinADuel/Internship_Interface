from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.deps import get_gmail_client_factory
from app.main import app
from app.models.application import Application, ApplicationStatus
from app.models.contact import Contact, ContactKind, ContactStatus
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.services import settings_service
from app.services.gmail.client import GmailError
from app.services.gmail.sync import GMAIL_LOCK_KEY
from app.services.sheet_sync_service import CONTACT_TABS, TAB_APPLICATIONS, TAB_INTERVIEWS
from tests.services.gmail.fakes import FakeGmailClient, grant_gmail, message

ROUTES = [
    ("GET", "/api/email/suggestions"),
    ("POST", "/api/email/suggestions/{suggestion_id}/accept"),
    ("POST", "/api/email/suggestions/{suggestion_id}/dismiss"),
    ("GET", "/api/email/status"),
    ("POST", "/api/email/sync"),
    ("GET", "/api/email/highlights"),
    ("GET", "/api/email/accounts"),
    ("DELETE", "/api/email/accounts/{account_id}"),
]
# Concrete paths for the auth and Claude-token boundary tests.
PATHS = [(method, path.replace("{suggestion_id}", "1").replace("{account_id}", "1")) for method, path in ROUTES]
RECEIVED = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)
K = SuggestionKind


def test_routes_list_is_complete():
    from app.api.email import router

    served = {(method, route.path) for route in router.routes for method in route.methods - {"HEAD", "OPTIONS"}}
    assert served == set(ROUTES)


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_every_route_requires_a_session(client, method, path):
    assert client.request(method, path).status_code == 401


@pytest.fixture()
def gmail():
    fake = FakeGmailClient()
    app.dependency_overrides[get_gmail_client_factory] = lambda: fake.factory
    yield fake
    app.dependency_overrides.pop(get_gmail_client_factory, None)


@pytest.fixture()
def stripe(db_session):
    application = Application(company="Stripe", role_title="SWE Intern", status=ApplicationStatus.APPLIED)
    db_session.add(application)
    db_session.commit()
    return application


def _suggestion(db, kind, application=None, contact=None, n=1, **fields) -> EmailSuggestion:
    defaults = dict(
        gmail_message_id=f"m{n}",
        gmail_thread_id=f"18c2f0a{n}",
        received_at=RECEIVED,
        direction=EmailDirection.INBOUND,
        from_name="Stripe Recruiting",
        from_email="recruiting@stripe.com",
        subject="Interview invitation",
        snippet="<b>We'd like</b> to invite you to a technical interview",
        kind=kind,
        application_id=application.id if application else None,
        contact_id=contact.id if contact else None,
    )
    row = EmailSuggestion(**{**defaults, **fields})
    db.add(row)
    db.commit()
    return row


def test_list_shape(logged_in_client, db_session, stripe):
    s = _suggestion(db_session, K.INTERVIEW, stripe)

    r = logged_in_client.get("/api/email/suggestions")

    assert r.status_code == 200
    (body,) = r.json()
    assert body == {
        "id": s.id,
        "gmail_message_id": "m1",
        "gmail_thread_id": "18c2f0a1",
        "gmail_url": "https://mail.google.com/mail/u/0/#all/18c2f0a1",
        "account_email": None,
        "received_at": "2026-10-08T15:30:00Z",
        "direction": "inbound",
        "from_name": "Stripe Recruiting",
        "from_email": "recruiting@stripe.com",
        "subject": "Interview invitation",
        "snippet": "<b>We'd like</b> to invite you to a technical interview",
        "kind": "interview",
        "state": "pending",
        "application_id": stripe.id,
        "contact_id": None,
        "proposed_company": None,
        "proposed_role": None,
        "round_kind": "technical",
        "application": {
            "id": stripe.id,
            "company": "Stripe",
            "role_title": "SWE Intern",
            "status": "applied",
            "archived": False,
        },
        "contact": None,
        "created_at": body["created_at"],
        "decided_at": None,
    }


def test_list_filters(logged_in_client, db_session, stripe):
    contact = Contact(kind=ContactKind.COMPANY, name="Jane", organization="Stripe", email="j@stripe.com", status=ContactStatus.SENT)
    db_session.add(contact)
    db_session.commit()
    reply = _suggestion(db_session, K.CONTACT_REPLY, contact=contact, n=1)
    offer = _suggestion(db_session, K.OFFER, stripe, n=2, state=SuggestionState.DISMISSED, decided_at=RECEIVED)

    pending = logged_in_client.get("/api/email/suggestions").json()
    assert [s["id"] for s in pending] == [reply.id]
    assert pending[0]["contact"] == {"id": contact.id, "name": "Jane", "organization": "Stripe", "status": "sent"}
    assert pending[0]["round_kind"] is None
    assert [s["id"] for s in logged_in_client.get("/api/email/suggestions?state=decided").json()] == [offer.id]
    assert [s["id"] for s in logged_in_client.get(f"/api/email/suggestions?state=all&application_id={stripe.id}").json()] == [offer.id]


@pytest.mark.parametrize("query", ["state=stale", "state=bogus", "limit=0", "limit=201", "application_id=x"])
def test_list_validation(logged_in_client, query):
    assert logged_in_client.get(f"/api/email/suggestions?{query}").status_code == 422


def test_accept_without_a_body(logged_in_client, db_session, stripe, sheet_sync_recorder):
    s = _suggestion(db_session, K.REJECTION, stripe, snippet="Unfortunately")

    r = logged_in_client.post(f"/api/email/suggestions/{s.id}/accept")

    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "accepted" and body["decided_at"] is not None
    assert body["application"]["status"] == "rejected"
    assert sheet_sync_recorder.scheduled == [[TAB_APPLICATIONS]]


def test_accept_an_interview_with_the_round_form(logged_in_client, db_session, stripe, sheet_sync_recorder):
    s = _suggestion(db_session, K.INTERVIEW, stripe)
    when = datetime(2026, 10, 20, 17, tzinfo=UTC)

    r = logged_in_client.post(
        f"/api/email/suggestions/{s.id}/accept",
        json={"round": {"kind": "technical", "title": "Coding", "scheduled_at": when.isoformat(), "format": "video"}},
    )

    assert r.status_code == 200 and r.json()["application"]["status"] == "interview"
    rounds = logged_in_client.get(f"/api/interviews?application_id={stripe.id}").json()
    assert [(x["kind"], x["title"], x["format"]) for x in rounds] == [("technical", "Coding", "video")]
    assert sheet_sync_recorder.scheduled == [[TAB_APPLICATIONS, TAB_INTERVIEWS]]


def test_accept_validates_the_round_and_names(logged_in_client, db_session, stripe):
    s = _suggestion(db_session, K.INTERVIEW, stripe)
    for body in (
        {"round": {"kind": "lunch"}},
        {"round": {"duration_minutes": 1}},
        {"round": {"scheduled_at": "2026-10-20T17:00:00"}},  # needs a timezone
        {"company": ""},
        {"role_title": "x" * 201},
    ):
        assert logged_in_client.post(f"/api/email/suggestions/{s.id}/accept", json=body).status_code == 422, body
    assert db_session.get(EmailSuggestion, s.id).state == SuggestionState.PENDING


def test_accept_a_new_application_with_edited_names(logged_in_client, db_session):
    s = _suggestion(db_session, K.NEW_APPLICATION, proposed_company="Rivian", proposed_role=None)
    r = logged_in_client.post(f"/api/email/suggestions/{s.id}/accept", json={"role_title": "Software Intern"})
    assert r.status_code == 200
    assert r.json()["application"]["company"] == "Rivian" and r.json()["application"]["role_title"] == "Software Intern"


def test_accept_from_a_contact_schedules_contact_tabs_too(logged_in_client, db_session, stripe, sheet_sync_recorder):
    contact = Contact(kind=ContactKind.COMPANY, name="Jane", organization="Stripe", email="j@stripe.com", status=ContactStatus.SENT, application_id=stripe.id)
    db_session.add(contact)
    db_session.commit()
    s = _suggestion(db_session, K.OFFER, stripe, contact)

    body = logged_in_client.post(f"/api/email/suggestions/{s.id}/accept").json()

    assert body["contact"]["status"] == "replied" and body["application"]["status"] == "offer"
    assert sheet_sync_recorder.scheduled == [[TAB_APPLICATIONS, *CONTACT_TABS]]


def test_accept_and_dismiss_errors(logged_in_client, db_session, stripe, sheet_sync_recorder):
    assert logged_in_client.post("/api/email/suggestions/999999/accept").json() == {"detail": "email suggestion not found"}
    assert logged_in_client.post("/api/email/suggestions/999999/dismiss").status_code == 404

    s = _suggestion(db_session, K.ASSESSMENT, stripe, n=1)
    assert logged_in_client.post(f"/api/email/suggestions/{s.id}/dismiss").json()["state"] == "dismissed"
    for action in ("accept", "dismiss"):
        r = logged_in_client.post(f"/api/email/suggestions/{s.id}/{action}")
        assert r.status_code == 409 and r.json() == {"detail": "this suggestion was already decided"}

    stale = _suggestion(db_session, K.OFFER, stripe, n=2)
    stripe.status = ApplicationStatus.OFFER
    db_session.commit()
    r = logged_in_client.post(f"/api/email/suggestions/{stale.id}/accept")
    assert r.status_code == 409 and r.json() == {"detail": "this suggestion no longer applies"}
    assert db_session.get(EmailSuggestion, stale.id).state == SuggestionState.STALE
    assert sheet_sync_recorder.scheduled == []


def test_status(logged_in_client, db_session, stripe):
    _suggestion(db_session, K.INTERVIEW, stripe, n=1)
    _suggestion(db_session, K.OFFER, stripe, n=2, state=SuggestionState.ACCEPTED, decided_at=RECEIVED)
    r = logged_in_client.get("/api/email/status")
    assert r.json() == {
        "gmail_granted": False,
        "gmail_sync_enabled": False,
        "gmail_last_sync_at": None,
        "gmail_last_error": None,
        "pending_count": 1,
        "accounts": [],
    }


def _enable(db, auto_apply=False):
    row = settings_service.get_settings(db)
    row.gmail_sync_enabled = True
    row.gmail_auto_apply = auto_apply
    db.commit()


def test_sync_now_needs_gmail_and_the_setting(logged_in_client, db_session, gmail):
    _enable(db_session)
    r = logged_in_client.post("/api/email/sync")
    assert r.status_code == 400 and r.json() == {"detail": "connect Gmail in Settings first"}

    grant_gmail(db_session)
    settings_service.get_settings(db_session).gmail_sync_enabled = False
    db_session.commit()
    r = logged_in_client.post("/api/email/sync")
    assert r.status_code == 400 and r.json() == {"detail": "turn on Gmail sync in Settings first"}
    assert gmail.queries == []


def test_sync_now_runs_a_sync(logged_in_client, db_session, gmail, stripe, sheet_sync_recorder):
    _enable(db_session)
    inbox = grant_gmail(db_session)
    gmail.add(
        message(
            "a1",
            datetime.now(UTC) - timedelta(hours=2),
            from_="Stripe <recruiting@stripe.com>",
            subject="Your application",
            snippet="Unfortunately we will not be moving forward",
        )
    )

    r = logged_in_client.post("/api/email/sync")

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "gmail_granted": True,
        "gmail_sync_enabled": True,
        "gmail_last_sync_at": body["gmail_last_sync_at"],
        "gmail_last_error": None,
        "pending_count": 1,
        "ok": True,
        "fetched": 1,
        "suggested": 1,
        "auto_applied": 0,
        "more": False,
        "accounts": [
            {
                "id": inbox.id,
                "email": "me@gmail.com",
                "last_sync_at": body["gmail_last_sync_at"],
                "last_error": None,
                "created_at": body["accounts"][0]["created_at"],
            }
        ],
    }
    assert body["gmail_last_sync_at"] is not None
    assert sheet_sync_recorder.scheduled == []


def test_sync_now_schedules_the_sheet_for_auto_applied_changes(logged_in_client, db_session, gmail, sheet_sync_recorder):
    _enable(db_session, auto_apply=True)
    grant_gmail(db_session)
    contact = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Ramp", email="sam@ramp.com", status=ContactStatus.SENT)
    db_session.add(contact)
    db_session.commit()
    gmail.add(message("r1", datetime.now(UTC) - timedelta(hours=1), from_="Sam <sam@ramp.com>", subject="Re: hi"))

    body = logged_in_client.post("/api/email/sync").json()

    assert (body["suggested"], body["auto_applied"], body["pending_count"]) == (1, 1, 0)
    assert sheet_sync_recorder.scheduled == [list(CONTACT_TABS)]


def test_sync_now_reports_a_failed_run(logged_in_client, db_session, gmail):
    _enable(db_session)
    grant_gmail(db_session)

    def failing(query, max_ids):
        raise GmailError("gmail list rejected (status 401); reconnect this inbox in Settings", status=401)

    gmail.list_message_ids = failing
    body = logged_in_client.post("/api/email/sync").json()
    assert body["ok"] is False
    assert body["gmail_last_error"] == "me@gmail.com: gmail list rejected (status 401); reconnect this inbox in Settings"
    assert body["accounts"][0]["last_error"] == "gmail list rejected (status 401); reconnect this inbox in Settings"


def test_sync_now_is_409_while_a_sync_is_running(logged_in_client, db_session, gmail, _engine):
    _enable(db_session)
    grant_gmail(db_session)
    other = _engine.connect()
    try:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": GMAIL_LOCK_KEY}).scalar_one()
        r = logged_in_client.post("/api/email/sync")
        assert r.status_code == 409 and r.json() == {"detail": "a Gmail sync is already running"}
        assert gmail.queries == []
    finally:
        other.execute(text("SELECT pg_advisory_unlock_all()"))
        other.rollback()
        other.close()


# The Dashboard's Email replies block (Phase 7 spec §3).


@pytest.fixture()
def jane(db_session, stripe):
    contact = Contact(
        kind=ContactKind.COMPANY,
        name="Jane",
        organization="Stripe",
        email="jane@stripe.com",
        status=ContactStatus.SENT,
        application_id=stripe.id,
    )
    db_session.add(contact)
    db_session.commit()
    return contact


def _ids(tab) -> list[int]:
    return [item["id"] for item in tab["items"]]


def test_highlights_tab_rules(logged_in_client, db_session, stripe, jane):
    S = SuggestionState
    # A contact's reply that is also an interview invitation: both tabs.
    invite = _suggestion(db_session, K.INTERVIEW, stripe, jane, n=1)
    offer = _suggestion(db_session, K.OFFER, stripe, n=2, state=S.ACCEPTED, decided_at=RECEIVED)
    stale = _suggestion(db_session, K.REJECTION, stripe, n=3, state=S.STALE, decided_at=RECEIVED)
    _suggestion(db_session, K.REJECTION, stripe, n=4, state=S.DISMISSED, decided_at=RECEIVED)
    reply = _suggestion(db_session, K.CONTACT_REPLY, contact=jane, n=5, state=S.AUTO_APPLIED, decided_at=RECEIVED)
    # Mail you sent is never a reply, even to a contact.
    _suggestion(db_session, K.CONTACT_SENT, contact=jane, n=6, direction=EmailDirection.SENT)
    _suggestion(db_session, K.REJECTION, stripe, n=7, direction=EmailDirection.SENT)
    # Other kinds have no tab.
    _suggestion(db_session, K.CONFIRMATION, stripe, n=8)
    _suggestion(db_session, K.ASSESSMENT, stripe, n=9)
    _suggestion(db_session, K.NEW_APPLICATION, n=10, proposed_company="Rivian")

    r = logged_in_client.get("/api/email/highlights")

    assert r.status_code == 200
    body = r.json()
    assert body["gmail_granted"] is False
    tabs = body["tabs"]
    assert set(tabs) == {"replies", "interview", "offer", "rejection"}
    assert sorted(_ids(tabs["replies"])) == sorted([invite.id, reply.id]) and tabs["replies"]["count"] == 2
    assert (_ids(tabs["interview"]), tabs["interview"]["count"]) == ([invite.id], 1)
    assert (_ids(tabs["offer"]), tabs["offer"]["count"]) == ([offer.id], 1)
    assert (_ids(tabs["rejection"]), tabs["rejection"]["count"]) == ([stale.id], 1)
    # Items are full EmailSuggestionOut rows, with what they link to.
    (item,) = tabs["interview"]["items"]
    assert item["state"] == "pending" and item["contact"]["name"] == "Jane"
    assert item["application"]["company"] == "Stripe" and item["round_kind"] == "technical"
    assert item["gmail_url"] == "https://mail.google.com/mail/u/0/#all/18c2f0a1" and item["account_email"] is None


def test_highlights_newest_first_and_the_count_is_every_match(logged_in_client, db_session, stripe):
    old = _suggestion(db_session, K.REJECTION, stripe, n=1, received_at=RECEIVED - timedelta(days=3))
    first_tie = _suggestion(db_session, K.REJECTION, stripe, n=2)
    second_tie = _suggestion(db_session, K.REJECTION, stripe, n=3)
    newest = _suggestion(db_session, K.REJECTION, stripe, n=4, received_at=RECEIVED + timedelta(hours=1))

    tab = logged_in_client.get("/api/email/highlights?limit=3").json()["tabs"]["rejection"]
    assert tab["count"] == 4
    # Same date: the later id first.
    assert _ids(tab) == [newest.id, second_tie.id, first_tie.id]
    assert old.id not in _ids(tab)

    tabs = logged_in_client.get("/api/email/highlights").json()["tabs"]
    assert len(tabs["rejection"]["items"]) == 4
    assert {k: v["count"] for k, v in tabs.items()} == {"replies": 0, "interview": 0, "offer": 0, "rejection": 4}


def test_highlights_default_to_eight_rows(logged_in_client, db_session, stripe):
    for n in range(1, 11):
        _suggestion(db_session, K.OFFER, stripe, n=n, received_at=RECEIVED + timedelta(minutes=n))
    tab = logged_in_client.get("/api/email/highlights").json()["tabs"]["offer"]
    assert tab["count"] == 10 and len(tab["items"]) == 8


@pytest.mark.parametrize(("query", "status"), [("limit=0", 422), ("limit=21", 422), ("limit=x", 422), ("limit=1", 200), ("limit=20", 200)])
def test_highlights_limit(logged_in_client, query, status):
    assert logged_in_client.get(f"/api/email/highlights?{query}").status_code == status


def test_highlights_mark_pending_mail_that_no_longer_applies_as_out_of_date(logged_in_client, db_session, stripe):
    s = _suggestion(db_session, K.INTERVIEW, stripe)
    stripe.status = ApplicationStatus.REJECTED
    db_session.commit()
    (item,) = logged_in_client.get("/api/email/highlights").json()["tabs"]["interview"]["items"]
    assert item["id"] == s.id and item["state"] == "stale"


def test_highlights_link_each_email_to_its_inbox(logged_in_client, db_session, stripe):
    personal = grant_gmail(db_session, "me@gmail.com")
    school = grant_gmail(db_session, "me+jobs@school.edu")
    _suggestion(db_session, K.OFFER, stripe, n=1, gmail_account_id=personal.id, gmail_thread_id="aaa1")
    _suggestion(db_session, K.OFFER, stripe, n=2, gmail_account_id=school.id, gmail_thread_id="bbb2", received_at=RECEIVED + timedelta(hours=1))

    body = logged_in_client.get("/api/email/highlights").json()

    assert body["gmail_granted"] is True
    assert [(i["account_email"], i["gmail_url"]) for i in body["tabs"]["offer"]["items"]] == [
        ("me+jobs@school.edu", "https://mail.google.com/mail/u/me%2Bjobs@school.edu/#all/bbb2"),
        ("me@gmail.com", "https://mail.google.com/mail/u/me@gmail.com/#all/aaa1"),
    ]
    # The suggestions list carries the inbox too.
    listed = logged_in_client.get("/api/email/suggestions").json()
    assert {i["account_email"] for i in listed} == {"me@gmail.com", "me+jobs@school.edu"}


# Connected inboxes (Phase 7 spec §4).


def test_accounts_list_oldest_first(logged_in_client, db_session):
    assert logged_in_client.get("/api/email/accounts").json() == []
    carried = grant_gmail(db_session, None)
    school = grant_gmail(db_session, "me@school.edu")
    school.last_error = "gmail list rejected (status 401); reconnect this inbox in Settings"
    school.last_sync_at = RECEIVED
    db_session.commit()

    body = logged_in_client.get("/api/email/accounts").json()

    assert body == [
        {"id": carried.id, "email": None, "last_sync_at": None, "last_error": None, "created_at": body[0]["created_at"]},
        {
            "id": school.id,
            "email": "me@school.edu",
            "last_sync_at": "2026-10-08T15:30:00Z",
            "last_error": "gmail list rejected (status 401); reconnect this inbox in Settings",
            "created_at": body[1]["created_at"],
        },
    ]
    # Nothing secret leaves the server.
    assert all(set(a) == {"id", "email", "last_sync_at", "last_error", "created_at"} for a in body)
    status = logged_in_client.get("/api/email/status").json()
    assert status["accounts"] == body and status["gmail_granted"] is True


def test_removing_an_inbox_deletes_its_email_updates_only(logged_in_client, db_session, stripe):
    personal = grant_gmail(db_session, "me@gmail.com")
    school = grant_gmail(db_session, "me@school.edu")
    kept = _suggestion(db_session, K.OFFER, stripe, n=1, gmail_account_id=personal.id)
    gone = _suggestion(db_session, K.REJECTION, stripe, n=2, gmail_account_id=school.id)
    accepted = _suggestion(db_session, K.INTERVIEW, stripe, n=3, gmail_account_id=school.id)
    assert logged_in_client.post(f"/api/email/suggestions/{accepted.id}/accept").status_code == 200
    gone_ids = [gone.id, accepted.id]
    school_id = school.id
    school.last_error = "gmail list rejected (status 500)"
    settings_service.get_settings(db_session).gmail_last_error = "me@school.edu: gmail list rejected (status 500)"
    db_session.commit()

    r = logged_in_client.delete(f"/api/email/accounts/{school_id}")

    assert r.status_code == 204 and r.content == b""
    assert [a["email"] for a in logged_in_client.get("/api/email/accounts").json()] == ["me@gmail.com"]
    db_session.expire_all()
    assert db_session.get(EmailSuggestion, kept.id) is not None
    assert all(db_session.get(EmailSuggestion, i) is None for i in gone_ids)
    # What was accepted from it stays.
    db_session.refresh(stripe)
    assert stripe.status == ApplicationStatus.INTERVIEW
    # The run summary no longer names the removed inbox.
    assert logged_in_client.get("/api/email/status").json()["gmail_last_error"] is None

    assert logged_in_client.delete(f"/api/email/accounts/{school_id}").status_code == 404
    r = logged_in_client.delete("/api/email/accounts/999999")
    assert r.status_code == 404 and r.json() == {"detail": "gmail inbox not found"}


def test_removing_the_last_inbox_disconnects_gmail(logged_in_client, db_session):
    inbox = grant_gmail(db_session)
    assert logged_in_client.delete(f"/api/email/accounts/{inbox.id}").status_code == 204
    assert logged_in_client.get("/api/settings").json()["gmail_granted"] is False
    assert logged_in_client.get("/api/email/highlights").json()["gmail_granted"] is False


def test_remove_inbox_validation(logged_in_client):
    assert logged_in_client.delete("/api/email/accounts/x").status_code == 422
