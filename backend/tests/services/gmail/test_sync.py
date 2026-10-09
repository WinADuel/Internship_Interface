"""One Gmail sync run on Postgres against a fake Gmail (never the network)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.models.application import Application, ApplicationStatus
from app.models.contact import Contact, ContactKind, ContactStatus
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.services import settings_service
from app.services.errors import GoogleAuthError
from app.services.gmail import sync
from app.services.gmail.client import GMAIL_RECONNECT_HINT, GmailError, GmailMessage, GoogleGmailClient
from app.services.gmail.sync import (
    BASE_QUERY,
    GMAIL_LOCK_KEY,
    build_query,
    build_snapshot,
    parse_message,
    run_sync,
)
from tests.services.gmail.fakes import FakeGmailClient, grant_gmail, message, ms

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


@pytest.fixture()
def settings(db_session):
    row = settings_service.get_settings(db_session)
    row.gmail_sync_enabled = True
    db_session.commit()
    grant_gmail(db_session)
    return row


@pytest.fixture()
def stripe(db_session):
    app = Application(company="Stripe", role_title="Software Engineering Intern", status=ApplicationStatus.APPLIED)
    db_session.add(app)
    db_session.commit()
    return app


def _rejection(mid: str, when: datetime) -> GmailMessage:
    return message(
        mid,
        when,
        from_="Stripe Recruiting <recruiting@stripe.com>",
        subject="Your Stripe application",
        snippet="Unfortunately we will not be moving forward",
    )


def _newsletter(mid: str, when: datetime) -> GmailMessage:
    return message(mid, when, from_="Deals <deals@shop.com>", subject="Big sale")


def _suggestions(db) -> list[EmailSuggestion]:
    return list(db.scalars(select(EmailSuggestion).order_by(EmailSuggestion.id)))


def test_does_nothing_while_sync_is_off(db_session):
    grant_gmail(db_session)
    gmail = FakeGmailClient([_newsletter("a1", _ago(hours=1))])
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "disabled"
    assert gmail.queries == [] and gmail.gets == []


def test_does_nothing_until_gmail_is_granted(db_session):
    settings_service.get_settings(db_session).gmail_sync_enabled = True
    db_session.commit()

    def factory(db):
        raise AssertionError("no client without the Gmail permission")

    assert run_sync(db_session, factory, now=NOW).status == "not_granted"


def test_first_run_looks_back_and_stores_only_matched_mail(db_session, settings, stripe):
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=3)), _rejection("a2", _ago(days=2)), _newsletter("a3", _ago(days=1))])

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "ok" and report.error is None
    assert (report.listed, report.fetched, report.suggested) == (3, 3, 1)
    assert gmail.queries == [f"{BASE_QUERY} newer_than:30d"]
    assert gmail.gets == ["a1", "a2", "a3"]  # oldest first
    assert gmail.closed
    (row,) = _suggestions(db_session)
    assert (row.gmail_message_id, row.gmail_thread_id, row.kind, row.application_id, row.state) == (
        "a2",
        "ta2",
        SuggestionKind.REJECTION,
        stripe.id,
        SuggestionState.PENDING,
    )
    assert (row.from_name, row.from_email, row.direction) == ("Stripe Recruiting", "recruiting@stripe.com", EmailDirection.INBOUND)
    assert row.received_at == _ago(days=2)
    db_session.refresh(settings)
    assert settings.gmail_history_cursor == str(ms(_ago(days=1)))
    assert settings.gmail_last_sync_at == NOW and settings.gmail_last_error is None


def test_lookback_setting_and_later_runs_overlap_an_hour(db_session, settings, stripe):
    settings.gmail_lookback_days = 7
    db_session.commit()
    gmail = FakeGmailClient([_rejection("a1", _ago(days=2)), _newsletter("a2", _ago(hours=5))])
    run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.queries == [f"{BASE_QUERY} newer_than:7d"]

    gmail.add(_newsletter("a3", _ago(hours=1)))
    gmail.gets.clear()
    report = run_sync(db_session, gmail.factory, now=NOW)

    after = int((_ago(hours=5) - timedelta(hours=1)).timestamp())
    assert gmail.queries[-1] == f"{BASE_QUERY} after:{after}"
    # Only mail from an hour before the cursor on is listed; a stored
    # message is never fetched again, an unmatched one in the overlap is.
    assert gmail.gets == ["a2", "a3"]
    assert report.listed == 2 and len(_suggestions(db_session)) == 1


def test_stored_ids_are_never_fetched_again(db_session, settings, stripe):
    gmail = FakeGmailClient([_rejection("a1", _ago(minutes=30)), _newsletter("a2", _ago(minutes=10))])
    run_sync(db_session, gmail.factory, now=NOW)
    gmail.gets.clear()
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.gets == ["a2"] and report.listed == 1


def test_query_never_reaches_past_the_lookback():
    old_cursor = str(ms(_ago(days=200)))
    assert build_query(old_cursor, 30, NOW) == f"{BASE_QUERY} after:{int(_ago(days=30).timestamp())}"
    assert build_query("garbage", 30, NOW) == f"{BASE_QUERY} newer_than:30d"


def test_a_run_fetches_at_most_max_fetch_oldest_first(db_session, settings, stripe, monkeypatch):
    monkeypatch.setattr(sync, "MAX_FETCH", 2)
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=3)), _newsletter("a2", _ago(days=2)), _rejection("a3", _ago(days=1))])

    report = run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.gets == ["a1", "a2"] and report.more
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=2)))

    gmail.gets.clear()
    report = run_sync(db_session, gmail.factory, now=NOW)
    # a2 is inside the hour of overlap, so it is looked at again.
    assert gmail.gets == ["a2", "a3"] and report.suggested == 1 and not report.more


def test_an_error_mid_run_keeps_what_was_done_and_the_next_run_continues(db_session, settings, stripe):
    gmail = FakeGmailClient(
        [_rejection("a1", _ago(days=3)), _newsletter("a2", _ago(days=2)), _rejection("a3", _ago(days=1))],
        fail_on={"a2": GmailError("gmail get rejected (status 429); it will retry next run", status=429)},
    )
    settings.gmail_last_sync_at = _ago(days=1)
    db_session.commit()

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "error"
    assert report.error == "gmail get rejected (status 429); it will retry next run"
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1"]
    row = settings_service.get_settings(db_session)
    assert row.gmail_history_cursor == str(ms(_ago(days=3)))
    assert row.gmail_last_error == report.error
    assert row.gmail_last_sync_at == _ago(days=1)  # only a clean run moves it

    gmail.fail_on.clear()
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok"
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1", "a3"]
    row = settings_service.get_settings(db_session)
    assert row.gmail_last_error is None and row.gmail_last_sync_at == NOW


def test_a_deleted_message_is_skipped(db_session, settings):
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))])
    gmail.messages["gone"] = None  # listed, then deleted before the fetch
    gmail.list_message_ids = lambda query, max_ids: (["a1", "gone"], False)
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok" and report.fetched == 1


def test_google_refusing_the_token_says_reconnect(db_session, settings):
    def factory(db):
        raise GoogleAuthError("google token request rejected (status 400)")

    report = run_sync(db_session, factory, now=NOW)
    assert report.status == "error"
    assert report.error == f"google token request rejected (status 400); {GMAIL_RECONNECT_HINT}"
    assert settings_service.get_settings(db_session).gmail_last_error == report.error


def test_an_unexpected_crash_is_recorded_by_type_only(db_session, settings):
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))], fail_on={"a1": RuntimeError("secret detail")})
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.error == "gmail sync failed unexpectedly (RuntimeError)"
    assert gmail.closed


def test_the_real_client_only_ever_asks_for_metadata(db_session, settings, stripe, monkeypatch):
    requests: list[httpx.Request] = []
    full = {
        "id": "18c1",
        "threadId": "18c0",
        "internalDate": str(ms(_ago(days=1))),
        "labelIds": ["INBOX"],
        "snippet": "Unfortunately we will not be moving forward",
        "payload": {"headers": [{"name": "From", "value": "Stripe <jobs@stripe.com>"}, {"name": "Subject", "value": "Your application"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "18c1"}]})
        return httpx.Response(200, json=full)

    report = run_sync(db_session, lambda db: GoogleGmailClient("tok", transport=httpx.MockTransport(handler)), now=NOW)

    assert report.suggested == 1
    assert len(requests) == 2
    for request in requests:
        assert request.method == "GET"
        assert request.url.params.get("format") in (None, "metadata")
        assert "full" not in str(request.url) and "raw" not in str(request.url)
        assert "attachments" not in request.url.path


def test_busy_while_another_run_holds_the_lock(db_session, settings, _engine):
    other = _engine.connect()
    try:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": GMAIL_LOCK_KEY}).scalar_one()
        gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))])
        report = run_sync(db_session, gmail.factory, now=NOW)
        assert report.status == "busy" and gmail.queries == []
    finally:
        other.execute(text("SELECT pg_advisory_unlock_all()"))
        other.rollback()
        other.close()
    # Released after a normal run, too.
    run_sync(db_session, FakeGmailClient().factory, now=NOW)
    check = _engine.connect()
    try:
        assert check.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": GMAIL_LOCK_KEY}).scalar_one()
        check.execute(text("SELECT pg_advisory_unlock_all()"))
    finally:
        check.rollback()
        check.close()


def _decided(db, mid: str, state: SuggestionState, decided_at: datetime | None) -> None:
    db.add(
        EmailSuggestion(
            gmail_message_id=mid,
            gmail_thread_id="t",
            received_at=_ago(days=200),
            direction=EmailDirection.INBOUND,
            kind=SuggestionKind.REJECTION,
            state=state,
            decided_at=decided_at,
        )
    )
    db.commit()


def test_retention_deletes_decisions_older_than_90_days_even_while_off(db_session):
    _decided(db_session, "old-accepted", SuggestionState.ACCEPTED, _ago(days=91))
    _decided(db_session, "old-dismissed", SuggestionState.DISMISSED, _ago(days=120))
    _decided(db_session, "old-stale", SuggestionState.STALE, _ago(days=91))
    _decided(db_session, "old-auto", SuggestionState.AUTO_APPLIED, _ago(days=91))
    _decided(db_session, "recent", SuggestionState.ACCEPTED, _ago(days=89))
    _decided(db_session, "pending", SuggestionState.PENDING, None)

    report = run_sync(db_session, FakeGmailClient().factory, now=NOW)

    assert report.status == "disabled" and report.deleted == 4
    assert {s.gmail_message_id for s in _suggestions(db_session)} == {"recent", "pending"}


def test_parse_message_decodes_cleans_and_caps():
    raw = message(
        "m1",
        NOW,
        from_='"=?UTF-8?B?Sm9zw6kgTMOzcGV6?=" <Jose@Example.COM>',
        subject="=?UTF-8?Q?Caf=C3=A9_interview?=\r\n\tnext\x00 week " + "x" * 400,
        snippet="We&#39;d like &lt;b&gt;you&lt;/b&gt;\n" + "y" * 400,
        to='"Doe, Jane" <jane@a.com>, bob@b.com, not-an-address',
        cc="Carol <carol@c.com>",
    )
    headers = parse_message(raw)
    assert headers.direction == EmailDirection.INBOUND
    assert headers.from_name == "José López"
    assert headers.from_email == "jose@example.com"
    assert headers.subject.startswith("Café interview next week xxx") and len(headers.subject) == 300
    assert headers.snippet.startswith("We'd like <b>you</b> yyy") and len(headers.snippet) == 300
    assert headers.to_emails == ("jane@a.com", "bob@b.com")
    assert headers.cc_emails == ("carol@c.com",)
    assert headers.received_at == NOW


def test_parse_message_sent_label_and_missing_headers():
    raw = GmailMessage(id="m", thread_id="t", internal_date=ms(NOW), label_ids=("SENT",), headers={}, snippet="")
    headers = parse_message(raw)
    assert headers.direction == EmailDirection.SENT
    assert (headers.from_name, headers.from_email, headers.subject, headers.to_emails) == ("", "", "", ())


def test_sent_mail_to_a_contact_is_matched(db_session, settings):
    contact = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Ramp", email="sam@ramp.com")
    db_session.add(contact)
    db_session.commit()
    gmail = FakeGmailClient([message("s1", _ago(days=1), from_="Me <me@gmail.com>", to="Sam <SAM@ramp.com>", labels=("SENT",))])

    run_sync(db_session, gmail.factory, now=NOW)

    (row,) = _suggestions(db_session)
    assert (row.kind, row.contact_id, row.direction) == (SuggestionKind.CONTACT_SENT, contact.id, EmailDirection.SENT)


def test_snapshot_leaves_out_archived_contacts_and_contacts_without_email(db_session, stripe):
    kept = Contact(kind=ContactKind.COMPANY, name="A", organization="Stripe", email="a@stripe.com", status=ContactStatus.SENT)
    archived = Contact(kind=ContactKind.COMPANY, name="B", organization="Stripe", email="b@stripe.com", archived=True)
    no_email = Contact(kind=ContactKind.COMPANY, name="C", organization="Stripe")
    db_session.add_all([kept, archived, no_email])
    db_session.commit()

    snapshot = build_snapshot(db_session)

    assert [c.id for c in snapshot.contacts] == [kept.id]
    assert snapshot.contacts[0].status == ContactStatus.SENT
    assert [a.id for a in snapshot.applications] == [stripe.id]


def test_one_pending_add_suggestion_per_untracked_company(db_session, settings):
    def rivian(mid, when, subject, snippet):
        return message(mid, when, from_="Rivian <no-reply@greenhouse.io>", subject=subject, snippet=snippet)

    gmail = FakeGmailClient(
        [
            rivian("r1", _ago(days=3), "Thank you for applying to Rivian", ""),
            rivian("r2", _ago(days=2), "Rivian interview", "Please share your availability"),
        ]
    )
    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.suggested == 1
    (row,) = _suggestions(db_session)
    assert (row.kind, row.proposed_company) == (SuggestionKind.NEW_APPLICATION, "Rivian")


def test_the_real_client_factory_uses_a_fresh_access_token(db_session, monkeypatch):
    monkeypatch.setattr(sync, "get_valid_access_token", lambda db: "fresh-token")
    client = sync.google_gmail_client(db_session)
    try:
        assert isinstance(client, GoogleGmailClient)
        assert client._client.headers["authorization"] == "Bearer fresh-token"
    finally:
        client.close()
