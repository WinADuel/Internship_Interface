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
]
# Concrete paths for the auth and Claude-token boundary tests.
PATHS = [(method, path.replace("{suggestion_id}", "1")) for method, path in ROUTES]
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
    grant_gmail(db_session)
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
        raise GmailError("gmail list rejected (status 401); reconnect Google and allow Gmail in Settings", status=401)

    gmail.list_message_ids = failing
    body = logged_in_client.post("/api/email/sync").json()
    assert body["ok"] is False
    assert body["gmail_last_error"] == "gmail list rejected (status 401); reconnect Google and allow Gmail in Settings"


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
