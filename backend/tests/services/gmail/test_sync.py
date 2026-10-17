"""One Gmail sync run on Postgres against a fake Gmail (never the network)."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import delete, select, text

from app.db.session import engine as app_engine
from app.models.application import Application, ApplicationStatus
from app.models.contact import Contact, ContactKind, ContactStatus
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.services import settings_service
from app.services.errors import GoogleAuthError
from app.services.gmail import sync
from app.services.google_docs_service import GOOGLE_SCOPE, store_token
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
from app.models.gmail_account import GmailAccount
from app.services.sheet_sync_service import CONTACT_TABS
from tests.services.gmail.fakes import FakeGmailClient, FakeInboxes, grant_gmail, message, ms

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


def _inbox(db) -> GmailAccount:
    db.expire_all()
    return db.scalars(select(GmailAccount)).one()


def _cursor(db) -> str | None:
    return _inbox(db).history_cursor


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

    def factory(db, account):
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
    assert _cursor(db_session) == str(ms(_ago(days=1)))
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
    assert _cursor(db_session) == str(ms(_ago(days=2)))

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
    assert report.error == "me@gmail.com: gmail get rejected (status 429); it will retry next run"
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1"]
    row = settings_service.get_settings(db_session)
    assert _cursor(db_session) == str(ms(_ago(days=3)))
    assert row.gmail_last_error == report.error
    assert _inbox(db_session).last_error == "gmail get rejected (status 429); it will retry next run"
    assert row.gmail_last_sync_at == _ago(days=1)  # only a clean run moves it

    gmail.fail_on.clear()
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok"
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["a1", "a3"]
    row = settings_service.get_settings(db_session)
    assert row.gmail_last_error is None and row.gmail_last_sync_at == NOW
    assert _inbox(db_session).last_error is None and _inbox(db_session).last_sync_at == NOW


def test_a_deleted_message_is_skipped(db_session, settings):
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))])
    gmail.messages["gone"] = None  # listed, then deleted before the fetch
    gmail.list_message_ids = lambda query, max_ids: (["a1", "gone"], False)
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok" and report.fetched == 1


def test_google_refusing_the_token_says_reconnect_this_inbox(db_session, settings):
    def factory(db, account):
        raise GoogleAuthError("google token request rejected (status 400)", reconnect=True)

    report = run_sync(db_session, factory, now=NOW)
    assert report.status == "error"
    assert GMAIL_RECONNECT_HINT == "reconnect this inbox in Settings"
    assert _inbox(db_session).last_error == f"google token request rejected (status 400); {GMAIL_RECONNECT_HINT}"
    assert report.error == f"me@gmail.com: google token request rejected (status 400); {GMAIL_RECONNECT_HINT}"
    assert settings_service.get_settings(db_session).gmail_last_error == report.error


def test_a_google_outage_says_it_will_retry(db_session, settings):
    def factory(db, account):
        raise GoogleAuthError("google token request rejected (status 503)")

    run_sync(db_session, factory, now=NOW)
    assert _inbox(db_session).last_error == "google token request rejected (status 503); it will retry next run"


def test_an_unexpected_crash_is_recorded_by_type_only(db_session, settings):
    gmail = FakeGmailClient([_newsletter("a1", _ago(days=1))])

    def broken_list(query, max_ids):
        raise RuntimeError("secret detail")

    gmail.list_message_ids = broken_list
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.error == "me@gmail.com: gmail sync failed unexpectedly (RuntimeError)"
    assert gmail.closed


def test_a_message_that_always_fails_is_skipped_and_logged_by_type_and_id_only(
    db_session, settings, stripe, monkeypatch, caplog
):
    """One bad message must not block later mail, and what is logged must
    not quote the email (a database error's text can carry its fields)."""
    real_store = sync.store_suggestion

    def store(db, message, headers, proposal, account_id):
        if message.id == "a2":
            raise sqlalchemy_exc.StatementError(
                "insert failed", "INSERT ...", {"subject": headers.subject}, ValueError("Secret subject")
            )
        return real_store(db, message, headers, proposal, account_id)

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
    assert _cursor(db_session) == str(ms(_ago(days=1)))
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
    assert _cursor(db_session) == str(ms(_ago(days=3)))
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert [s.gmail_message_id for s in _suggestions(db_session)] == ["first", "late"]
    assert not report.more
    assert _cursor(db_session) == str(ms(_ago(days=2)))


def test_an_error_stop_moves_the_cursor_only_to_the_last_message_handled(db_session, settings, stripe):
    gmail = _out_of_order(fail_on={"late": GmailError("gmail get rejected (status 500)", status=500)})

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "error"
    assert _cursor(db_session) == str(ms(_ago(days=3)))
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
    assert _cursor(db_session) == str(ms(_ago(days=3)))

    gmail.gets.clear()
    run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.gets == ["first", "mid"]
    assert _cursor(db_session) == str(ms(_ago(days=1)))


def test_a_complete_run_moves_the_cursor_to_the_newest_message(db_session, settings, stripe):
    run_sync(db_session, _out_of_order().factory, now=NOW)
    assert _cursor(db_session) == str(ms(_ago(days=1)))


def test_a_future_dated_message_does_not_move_the_cursor_past_now(db_session, settings, stripe):
    gmail = FakeGmailClient([_newsletter("future", NOW + timedelta(days=30))])
    run_sync(db_session, gmail.factory, now=NOW)
    assert _cursor(db_session) == str(ms(NOW))

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
    assert _cursor(db_session) == str(ms(_ago(days=2)))
    assert row.gmail_last_sync_at is None and row.gmail_last_error is None
    assert _inbox(db_session).last_sync_at is None
    assert gmail.closed


def test_removing_the_only_inbox_stops_a_running_sync_and_says_so(db_session, settings, stripe):
    def remove_inbox():
        db_session.execute(delete(GmailAccount))
        db_session.flush()

    gmail = _Hooked(_three(), "a1", remove_inbox)

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "not_granted" and gmail.gets == ["a1"]
    assert settings_service.get_settings(db_session).gmail_last_error == GMAIL_PERMISSION_MISSING
    assert _suggestions(db_session) == []


def test_reconnecting_google_docs_does_not_stop_gmail_sync(db_session, settings, stripe):
    def drive_only_reconnect():
        store_token(db_session, {"refresh_token": "refresh"}, GOOGLE_SCOPE)

    gmail = _Hooked(_three(), "a1", drive_only_reconnect)
    report = run_sync(db_session, gmail.factory, now=NOW)
    assert report.status == "ok" and gmail.gets == ["a1", "a2", "a3"]


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

    report = run_sync(db_session, lambda db, account: GoogleGmailClient("tok", transport=httpx.MockTransport(handler)), now=NOW)

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


def test_the_real_client_factory_uses_the_inboxs_own_token(db_session, monkeypatch):
    other = grant_gmail(db_session, "other@gmail.com", refresh_token="other-refresh")
    calls = []

    def post(url, data=None, **kwargs):
        calls.append(data)
        return httpx.Response(200, json={"access_token": "fresh-token"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    client = sync.google_gmail_client(db_session, other)
    try:
        assert isinstance(client, GoogleGmailClient)
        assert client._client.headers["authorization"] == "Bearer fresh-token"
    finally:
        client.close()
    assert [c["refresh_token"] for c in calls] == ["other-refresh"]


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


# More than one inbox (Phase 7 spec §4).


@pytest.fixture()
def two_inboxes(db_session, settings):
    """The settings fixture's inbox (me@gmail.com) and a school one."""
    personal = db_session.scalars(select(GmailAccount)).one()
    school = grant_gmail(db_session, "me@school.edu")
    return personal, school


def _by_inbox(db) -> list[tuple[int, str]]:
    return [(s.gmail_account_id, s.gmail_message_id) for s in _suggestions(db)]


def _account(db, account_id) -> GmailAccount | None:
    db.expire_all()
    return db.get(GmailAccount, account_id)


def test_every_inbox_is_synced_oldest_first_with_its_own_cursor(db_session, two_inboxes, stripe):
    personal, school = two_inboxes
    # Message ids are per mailbox: the same id in two inboxes is two emails.
    a = FakeGmailClient([_rejection("x1", _ago(days=3)), _newsletter("a2", _ago(days=2))])
    b = FakeGmailClient([_rejection("x1", _ago(days=1))], address="me@school.edu")
    inboxes = FakeInboxes({personal.id: a, school.id: b})

    report = run_sync(db_session, inboxes, now=NOW)

    assert report.status == "ok" and report.error is None
    assert inboxes.opened == [personal.id, school.id]
    assert (report.listed, report.fetched, report.suggested) == (3, 3, 2)  # summed over inboxes
    assert sorted(_by_inbox(db_session)) == sorted([(personal.id, "x1"), (school.id, "x1")])
    assert _account(db_session, personal.id).history_cursor == str(ms(_ago(days=2)))
    assert _account(db_session, school.id).history_cursor == str(ms(_ago(days=1)))
    assert a.closed and b.closed
    assert [i.status for i in report.inboxes] == ["ok", "ok"]
    for account_id in (personal.id, school.id):
        assert _account(db_session, account_id).last_sync_at == NOW
    row = settings_service.get_settings(db_session)
    assert row.gmail_last_sync_at == NOW and row.gmail_last_error is None

    # The next run asks each inbox from its own cursor, and a message stored
    # for one inbox isn't fetched again from it.
    a.gets.clear()
    b.gets.clear()
    run_sync(db_session, inboxes, now=NOW)
    assert a.queries[-1] == f"{BASE_QUERY} after:{int((_ago(days=2) - timedelta(hours=1)).timestamp())}"
    assert b.queries[-1] == f"{BASE_QUERY} after:{int((_ago(days=1) - timedelta(hours=1)).timestamp())}"
    assert a.gets == ["a2"] and b.gets == []


def test_one_inbox_failing_does_not_stop_the_other(db_session, two_inboxes, stripe):
    personal, school = two_inboxes
    settings_service.get_settings(db_session).gmail_last_sync_at = _ago(days=1)
    db_session.commit()
    b = FakeGmailClient([_rejection("b1", _ago(days=1))], address="me@school.edu")
    refused = GoogleAuthError("google token request rejected (status 400)", reconnect=True)
    inboxes = FakeInboxes({personal.id: refused, school.id: b})

    report = run_sync(db_session, inboxes, now=NOW)

    assert report.status == "error"
    assert inboxes.opened == [personal.id, school.id]
    assert _by_inbox(db_session) == [(school.id, "b1")]
    failed = _account(db_session, personal.id)
    assert failed.last_error == "google token request rejected (status 400); reconnect this inbox in Settings"
    assert failed.last_sync_at is None
    synced = _account(db_session, school.id)
    assert synced.last_error is None and synced.last_sync_at == NOW
    row = settings_service.get_settings(db_session)
    # At least one inbox synced; the error names the failing one.
    assert row.gmail_last_sync_at == NOW
    assert row.gmail_last_error == report.error == (
        "me@gmail.com: google token request rejected (status 400); reconnect this inbox in Settings"
    )

    # Fixed: the next run clears both.
    inboxes.by_account[personal.id] = FakeGmailClient()
    assert run_sync(db_session, inboxes, now=NOW).status == "ok"
    assert _account(db_session, personal.id).last_error is None
    assert settings_service.get_settings(db_session).gmail_last_error is None


def test_a_gmail_error_mid_inbox_keeps_its_progress_and_moves_on(db_session, two_inboxes, stripe):
    personal, school = two_inboxes
    a = FakeGmailClient(
        [_rejection("a1", _ago(days=3)), _newsletter("a2", _ago(days=2))],
        fail_on={"a2": GmailError("gmail get rejected (status 500); it will retry next run", status=500)},
    )
    b = FakeGmailClient([_rejection("b1", _ago(days=1))], fail_on={"b1": GmailError("gmail get rejected (status 429)", status=429)})
    report = run_sync(db_session, FakeInboxes({personal.id: a, school.id: b}), now=NOW)

    assert _by_inbox(db_session) == [(personal.id, "a1")]
    assert _account(db_session, personal.id).history_cursor == str(ms(_ago(days=3)))
    assert _account(db_session, school.id).history_cursor is None
    assert report.error == (
        "me@gmail.com: gmail get rejected (status 500); it will retry next run;"
        " me@school.edu: gmail get rejected (status 429)"
    )
    # No inbox synced cleanly: the summary's last-sync time stays.
    assert settings_service.get_settings(db_session).gmail_last_sync_at is None


def test_an_inbox_carried_over_from_phase_6_learns_its_address(db_session, settings, stripe):
    carried = db_session.scalars(select(GmailAccount)).one()
    carried.email = None
    db_session.commit()
    gmail = FakeGmailClient([_rejection("a1", _ago(days=1))], address="me@gmail.com")

    report = run_sync(db_session, gmail.factory, now=NOW)

    assert report.status == "ok" and gmail.profiles == 1
    assert _account(db_session, carried.id).email == "me@gmail.com"
    assert _by_inbox(db_session) == [(carried.id, "a1")]
    run_sync(db_session, gmail.factory, now=NOW)
    assert gmail.profiles == 1  # only while the address is unknown


def test_a_carried_over_inbox_already_connected_again_merges_into_it(db_session, settings, stripe):
    carried = db_session.scalars(select(GmailAccount)).one()
    carried.email = None
    carried.history_cursor = str(ms(_ago(days=5)))
    db_session.commit()
    again = grant_gmail(db_session, "me@gmail.com")  # Connect Gmail with the same account
    for n, (account, mid) in enumerate([(carried, "old1"), (carried, "both"), (again, "both")]):
        db_session.add(
            EmailSuggestion(
                gmail_account_id=account.id,
                gmail_message_id=mid,
                gmail_thread_id=f"t{n}",
                received_at=_ago(days=4),
                direction=EmailDirection.INBOUND,
                kind=SuggestionKind.REJECTION,
                application_id=stripe.id,
            )
        )
    db_session.commit()
    old_inbox = FakeGmailClient(address="me@gmail.com")
    new_inbox = FakeGmailClient([_rejection("new1", _ago(days=1))], address="me@gmail.com")
    inboxes = FakeInboxes({carried.id: old_inbox, again.id: new_inbox})

    report = run_sync(db_session, inboxes, now=NOW)

    assert report.status == "ok"
    assert inboxes.opened == [carried.id, again.id]
    assert old_inbox.queries == [] and old_inbox.closed
    assert _account(db_session, carried.id) is None
    assert sorted(_by_inbox(db_session)) == sorted([(again.id, "old1"), (again.id, "both"), (again.id, "new1")])
    assert [i.status for i in report.inboxes] == ["merged", "ok"]


def test_a_profile_failure_is_recorded_on_that_inbox(db_session, two_inboxes):
    personal, school = two_inboxes
    personal.email = None
    db_session.commit()

    class NoProfile(FakeGmailClient):
        def get_profile(self):
            raise GmailError("gmail profile rejected (status 401); reconnect this inbox in Settings", status=401)

    b = FakeGmailClient(address="me@school.edu")
    report = run_sync(db_session, FakeInboxes({personal.id: NoProfile(), school.id: b}), now=NOW)

    assert _account(db_session, personal.id).email is None
    assert report.error == "Gmail inbox: gmail profile rejected (status 401); reconnect this inbox in Settings"
    assert b.queries and _account(db_session, school.id).last_sync_at == NOW


def test_removing_one_inbox_mid_run_stops_only_its_turn(db_session, two_inboxes, stripe):
    personal, school = two_inboxes
    personal_id = personal.id

    def remove_personal():
        db_session.execute(delete(GmailAccount).where(GmailAccount.id == personal_id))
        db_session.flush()

    a = _Hooked(_three(), "a1", remove_personal)
    b = FakeGmailClient([_rejection("b1", _ago(days=1))], address="me@school.edu")
    report = run_sync(db_session, FakeInboxes({personal_id: a, school.id: b}), now=NOW)

    assert report.status == "ok" and report.error is None
    assert a.gets == ["a1"] and a.closed
    assert [i.status for i in report.inboxes] == ["removed", "ok"]
    assert _by_inbox(db_session) == [(school.id, "b1")]
    assert settings_service.get_settings(db_session).gmail_last_sync_at == NOW


def test_turning_sync_off_mid_run_ends_the_whole_run(db_session, two_inboxes, stripe):
    personal, school = two_inboxes

    def turn_off():
        settings_service.get_settings(db_session).gmail_sync_enabled = False
        db_session.flush()

    a = _Hooked(_three(), "a2", turn_off)
    inboxes = FakeInboxes({personal.id: a, school.id: FakeGmailClient(address="me@school.edu")})

    report = run_sync(db_session, inboxes, now=NOW)

    assert report.status == "disabled" and inboxes.opened == [personal.id]
    assert _account(db_session, personal.id).history_cursor == str(ms(_ago(days=2)))
    assert _account(db_session, personal.id).last_sync_at is None
    assert settings_service.get_settings(db_session).gmail_last_sync_at is None


def test_mail_from_any_inbox_is_matched_against_the_same_contacts(db_session, two_inboxes):
    personal, school = two_inboxes
    settings_service.get_settings(db_session).gmail_auto_apply = True
    contact = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Ramp", email="sam@ramp.com")
    db_session.add(contact)
    db_session.commit()
    # The cold email went out from the school inbox; Sam replies to it there,
    # and a later note arrives at the personal one.
    a = FakeGmailClient([message("r2", _ago(hours=1), from_="Sam <sam@ramp.com>", subject="Re: hi again")])
    b = FakeGmailClient(
        [
            message("s1", _ago(days=2), from_="Me <me@school.edu>", to="sam@ramp.com", labels=("SENT",)),
            message("r1", _ago(days=1), from_="Sam <sam@ramp.com>", subject="Re: hello", snippet="Happy to chat"),
        ],
        address="me@school.edu",
    )
    run_sync(db_session, FakeInboxes({personal.id: a, school.id: b}), now=NOW)

    db_session.refresh(contact)
    assert contact.status == ContactStatus.REPLIED
    kinds = {(s.gmail_account_id, s.gmail_message_id): s.kind for s in _suggestions(db_session)}
    assert kinds[(school.id, "s1")] == SuggestionKind.CONTACT_SENT
    assert kinds[(school.id, "r1")] == SuggestionKind.CONTACT_REPLY


def test_mail_held_by_an_unaddressed_inbox_or_no_inbox_is_not_suggested_again(db_session, two_inboxes, stripe):
    """The Phase 6 inbox can't learn its address (its token broke) and was
    reconnected as a new inbox: the new one's first sync must not bring back
    what the old one already holds, accepted or not."""
    personal, school = two_inboxes
    carried = grant_gmail(db_session, None, refresh_token="broken")
    db_session.add_all(
        [
            EmailSuggestion(
                gmail_account_id=account_id,
                gmail_message_id=mid,
                gmail_thread_id=f"t{mid}",
                received_at=_ago(days=3),
                direction=EmailDirection.INBOUND,
                kind=SuggestionKind.REJECTION,
                application_id=stripe.id,
                state=SuggestionState.ACCEPTED,
                decided_at=_ago(days=2),
            )
            for account_id, mid in ((carried.id, "a1"), (None, "a2"))
        ]
    )
    db_session.commit()
    a = FakeGmailClient([_rejection("a1", _ago(days=3)), _rejection("a2", _ago(days=3)), _rejection("a3", _ago(days=1))])
    refused = GoogleAuthError("google token request rejected (status 400)", reconnect=True)
    b = FakeGmailClient(address="me@school.edu")

    run_sync(db_session, FakeInboxes({personal.id: a, school.id: b, carried.id: refused}), now=NOW)

    assert a.gets == ["a3"]
    assert set(_by_inbox(db_session)) == {(carried.id, "a1"), (None, "a2"), (personal.id, "a3")}


def test_turning_sync_off_between_inboxes_ends_the_run(db_session, two_inboxes):
    personal, school = two_inboxes

    class TurnsOffWhenDone(FakeGmailClient):
        def close(self):
            # As the Settings page would, in its own committed request.
            super().close()
            settings_service.get_settings(db_session).gmail_sync_enabled = False
            db_session.commit()

    inboxes = FakeInboxes({personal.id: TurnsOffWhenDone(), school.id: FakeGmailClient(address="me@school.edu")})

    report = run_sync(db_session, inboxes, now=NOW)

    assert report.status == "disabled" and inboxes.opened == [personal.id]
    assert _account(db_session, personal.id).last_sync_at == NOW  # its own turn was complete
    assert _account(db_session, school.id).last_sync_at is None
