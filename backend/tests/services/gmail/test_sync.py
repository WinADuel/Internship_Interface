"""One Gmail sync run on Postgres against a fake Gmail (never the network)."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import select, text

from app.db.session import engine as app_engine
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
    GMAIL_PERMISSION_MISSING,
    build_query,
    build_snapshot,
    parse_message,
    run_sync,
)
from app.services.google_docs_service import GOOGLE_SCOPE, store_token
from app.services.sheet_sync_service import CONTACT_TABS
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
    # Sync is on, so the missing permission is shown in Settings.
    row = settings_service.get_settings(db_session)
    assert row.gmail_last_error == GMAIL_PERMISSION_MISSING and row.gmail_last_sync_at is None


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
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))])

    def broken_list(query, max_ids):
        raise RuntimeError("secret detail")

    gmail.list_message_ids = broken_list
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.error == "gmail sync failed unexpectedly (RuntimeError)"
    assert gmail.closed


def test_a_message_that_always_fails_is_skipped_and_logged_by_type_and_id_only(
    db_session, settings, stripe, monkeypatch, caplog
):
    """One bad message must not block later mail, and what is logged must
    not quote the email (a database error's text can carry its fields)."""
    real_store = sync.store_suggestion

    def store(db, message, headers, proposal):
        if message.id == "a2":
            raise sqlalchemy_exc.StatementError(
                "insert failed", "INSERT ...", {"subject": headers.subject}, ValueError("Secret subject")
            )
        return real_store(db, message, headers, proposal)

    monkeypatch.setattr(sync, "store_suggestion", store)
    secret = message(
        "a2",
        _ago(days=2),
        from_="Stripe Recruiting <recruiting@stripe.com>",
        subject="Secret subject",
        snippet="Unfortunately we will not be moving forward",
    )
    gmail = FakeGmailClient([_rejection("a1", _ago(days=3)), secret, _rejection("a3", _ago(days=1))])

    with caplog.at_level(logging.DEBUG):
        report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "ok" and report.error is None
    assert (report.fetched, report.suggested, report.skipped) == (3, 2, 1)
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1", "a3"]
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=1)))
    logged = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert "gmail sync skipped message a2 (StatementError)" in logged
    assert "Secret" not in logged and "stripe.com" not in logged
    assert not any(r.exc_info for r in caplog.records)

    # Later runs are not blocked by it either.
    gmail.add(_rejection("a4", _ago(hours=2)))
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok" and [s.gmail_message_id for s in _suggestions(db_session)] == ["a1", "a3", "a4"]


def test_the_app_engine_hides_sql_parameters_in_errors():
    assert app_engine.hide_parameters is True


class _ListedInOrder(FakeGmailClient):
    """Lists its messages in the given order (Gmail's order is newest first,
    but not always strictly by `internalDate`)."""

    def __init__(self, messages, order, **kwargs):
        super().__init__(messages, **kwargs)
        self.order = order

    def list_message_ids(self, query, max_ids):
        self.queries.append(query)
        after = re.search(r"\bafter:(\d+)", query)
        since = int(after.group(1)) * 1000 if after else 0
        ids = [i for i in self.order if self.messages[i].internal_date > since]
        return ids[:max_ids], len(ids) > max_ids


def _out_of_order(first=None, **kwargs) -> _ListedInOrder:
    """Listed late, mid, first, so handled first, mid, late; but "first" is
    the newest and "mid" the oldest: the newest date handled is not where the
    run got to."""
    return _ListedInOrder(
        [first or _rejection("first", _ago(days=1)), _newsletter("mid", _ago(days=3)), _rejection("late", _ago(days=2))],
        ["late", "mid", "first"],
        **kwargs,
    )


def test_a_capped_run_moves_the_cursor_only_to_the_last_message_handled(db_session, settings, stripe, monkeypatch):
    monkeypatch.setattr(sync, "MAX_FETCH", 2)
    gmail = _out_of_order()

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert gmail.gets == ["first", "mid"] and report.more
    # Not the newest date handled (a day ago): "late" is older than that.
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=3)))
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["first", "late"]
    assert not report.more
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=2)))


def test_an_error_stop_moves_the_cursor_only_to_the_last_message_handled(db_session, settings, stripe):
    gmail = _out_of_order(fail_on={"late": GmailError("gmail get rejected (status 500)", status=500)})

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "error"
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=3)))
    gmail.fail_on.clear()
    run_sync(db_session, gmail.factory, now=NOW)
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["first", "late"]


def test_a_capped_run_that_cannot_move_the_cursor_still_makes_progress(db_session, settings, stripe, monkeypatch):
    """When the oldest end of the list is out of order and unmatched, the
    same messages would be handled again every run: the cursor then moves
    to the newest date seen instead."""
    monkeypatch.setattr(sync, "MAX_FETCH", 2)
    gmail = _out_of_order(first=_newsletter("first", _ago(days=1)))
    run_sync(db_session, gmail.factory, now=NOW)
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=3)))

    gmail.gets.clear()
    run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.gets == ["first", "mid"]
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=1)))


def test_a_complete_run_moves_the_cursor_to_the_newest_message(db_session, settings, stripe):
    run_sync(db_session, _out_of_order().factory, now=NOW)
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(_ago(days=1)))


def test_a_future_dated_message_does_not_move_the_cursor_past_now(db_session, settings, stripe):
    gmail = FakeGmailClient([_newsletter("future", NOW + timedelta(days=30))])
    run_sync(db_session, gmail.factory, now=NOW)
    assert settings_service.get_settings(db_session).gmail_history_cursor == str(ms(NOW))

    # Mail that arrives later is still found.
    later = NOW + timedelta(hours=2)
    gmail.add(_rejection("a1", NOW + timedelta(hours=1)))
    run_sync(db_session, gmail.factory, now=later)
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1"]


class _Hooked(FakeGmailClient):
    """Runs `hook` right after fetching `on`."""

    def __init__(self, messages, on, hook):
        super().__init__(messages)
        self.on, self.hook = on, hook

    def get_metadata(self, message_id):
        result = super().get_metadata(message_id)
        if message_id == self.on:
            self.hook()
        return result


def _three() -> list[GmailMessage]:
    return [_newsletter("a1", _ago(days=3)), _newsletter("a2", _ago(days=2)), _rejection("a3", _ago(days=1))]


def test_turning_sync_off_stops_a_running_sync(db_session, settings, stripe):
    def turn_off():
        settings_service.get_settings(db_session).gmail_sync_enabled = False
        db_session.flush()

    gmail = _Hooked(_three(), "a2", turn_off)

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "disabled"
    assert gmail.gets == ["a1", "a2"] and _suggestions(db_session) == []
    row = settings_service.get_settings(db_session)
    assert row.gmail_history_cursor == str(ms(_ago(days=2)))
    assert row.gmail_last_sync_at is None and row.gmail_last_error is None
    assert gmail.closed


def test_losing_the_gmail_permission_stops_a_running_sync_and_says_so(db_session, settings, stripe):
    def drive_only_reconnect():
        store_token(db_session, {"refresh_token": "refresh"}, GOOGLE_SCOPE)

    gmail = _Hooked(_three(), "a1", drive_only_reconnect)

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "not_granted" and gmail.gets == ["a1"]
    row = settings_service.get_settings(db_session)
    assert row.gmail_last_error == GMAIL_PERMISSION_MISSING
    assert row.gmail_history_cursor == str(ms(_ago(days=3)))


def test_a_successful_run_clears_the_permission_error(db_session, settings):
    settings.gmail_last_error = GMAIL_PERMISSION_MISSING
    db_session.commit()
    run_sync(db_session, FakeGmailClient().factory, now=NOW)
    assert settings_service.get_settings(db_session).gmail_last_error is None


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


def test_auto_apply_in_a_run_and_the_snapshot_follows_it(db_session, settings):
    settings.gmail_auto_apply = True
    db_session.commit()
    contact = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Ramp", email="sam@ramp.com")
    db_session.add(contact)
    db_session.commit()
    gmail = FakeGmailClient(
        [
            message("s1", _ago(days=2), from_="Me <me@gmail.com>", to="sam@ramp.com", labels=("SENT",)),
            message("r1", _ago(days=1), from_="Sam <sam@ramp.com>", subject="Re: hello", snippet="Happy to chat"),
        ]
    )

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert (report.suggested, report.auto_applied) == (2, 2)
    assert report.sheet_tabs == set(CONTACT_TABS)
    assert [(s.kind, s.state) for s in _suggestions(db_session)] == [
        (SuggestionKind.CONTACT_SENT, SuggestionState.AUTO_APPLIED),
        (SuggestionKind.CONTACT_REPLY, SuggestionState.AUTO_APPLIED),
    ]
    db_session.refresh(contact)
    assert contact.status == ContactStatus.REPLIED
    assert contact.sent_at == _ago(days=2) and contact.replied_at == _ago(days=1)


def test_unsafe_kinds_wait_even_with_auto_apply(db_session, settings, stripe):
    settings.gmail_auto_apply = True
    db_session.commit()
    report = run_sync(db_session, FakeGmailClient([_rejection("a1", _ago(days=1))]).factory, now=NOW)
    assert (report.suggested, report.auto_applied) == (1, 0)
    assert _suggestions(db_session)[0].state == SuggestionState.PENDING
    db_session.refresh(stripe)
    assert stripe.status == ApplicationStatus.APPLIED


def test_a_suggestion_that_already_does_not_apply_is_kept_as_stale(db_session, settings, stripe):
    stripe.status = ApplicationStatus.REJECTED
    db_session.commit()
    run_sync(db_session, FakeGmailClient([_rejection("a1", _ago(days=1))]).factory, now=NOW)
    (row,) = _suggestions(db_session)
    assert row.state == SuggestionState.STALE  # kept so the message isn't fetched again
