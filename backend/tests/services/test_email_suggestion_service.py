"""Accepting, dismissing and staling email suggestions through the real
services on Postgres (Phase 6 spec §4 "Suggested actions")."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.application import Application, ApplicationStatus
from app.models.contact import Contact, ContactKind, ContactStatus
from app.models.email_suggestion import EmailDirection, EmailSuggestion, SuggestionKind, SuggestionState
from app.models.interview import InterviewKind, InterviewRound, InterviewState
from app.models.research_queue import ResearchQueueItem
from app.models.status_history import StatusHistory
from app.schemas.email import AcceptIn, SuggestionRoundIn
from app.services import email_suggestion_service as service
from app.services.errors import (
    EmailSuggestionNotFoundError,
    SuggestionNotPendingError,
    SuggestionStaleError,
)
from app.services.sheet_sync_service import CONTACT_TABS, ROUND_SYNC_TABS, TAB_APPLICATIONS

K = SuggestionKind
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)
_ids = iter(range(1, 10_000))


def _app(db, status=ApplicationStatus.APPLIED, company="Stripe", **fields) -> Application:
    app = Application(company=company, role_title="SWE Intern", status=status, **fields)
    db.add(app)
    db.commit()
    return app


def _contact(db, status=ContactStatus.SENT, application=None, **fields) -> Contact:
    contact = Contact(
        kind=ContactKind.COMPANY,
        name="Jane",
        organization="Stripe",
        email="jane@stripe.com",
        status=status,
        application_id=application.id if application else None,
        **fields,
    )
    db.add(contact)
    db.commit()
    return contact


def _suggestion(db, kind, application=None, contact=None, **fields) -> EmailSuggestion:
    n = next(_ids)
    defaults = dict(
        gmail_message_id=f"m{n}",
        gmail_thread_id=f"t{n}",
        received_at=RECEIVED,
        direction=EmailDirection.SENT if kind == K.CONTACT_SENT else EmailDirection.INBOUND,
        from_name="Stripe",
        from_email="jobs@stripe.com",
        subject="Hello",
        snippet="",
        kind=kind,
        application_id=application.id if application else None,
        contact_id=contact.id if contact else None,
    )
    suggestion = EmailSuggestion(**{**defaults, **fields})
    db.add(suggestion)
    db.commit()
    return suggestion


def _history(db, app) -> list[tuple]:
    rows = db.scalars(select(StatusHistory).where(StatusHistory.application_id == app.id).order_by(StatusHistory.id))
    return [(h.old_status, h.new_status) for h in rows]


# --- each kind -----------------------------------------------------------------


def test_confirmation_marks_a_wishlist_application_applied(db_session):
    app = _app(db_session, ApplicationStatus.WISHLIST)
    s = _suggestion(db_session, K.CONFIRMATION, app)

    result = service.accept(db_session, s.id, now=NOW)

    assert result.suggestion.state == SuggestionState.ACCEPTED and result.suggestion.decided_at == NOW
    assert result.sheet_tabs == {TAB_APPLICATIONS}
    db_session.refresh(app)
    assert app.status == ApplicationStatus.APPLIED and app.date_applied == date(2026, 10, 8)
    assert _history(db_session, app) == [(ApplicationStatus.WISHLIST, ApplicationStatus.APPLIED)]
    # Entering applied queues the find-contacts request, as a click does.
    assert db_session.scalar(select(ResearchQueueItem).where(ResearchQueueItem.application_id == app.id))


def test_confirmation_of_an_applied_application_only_fills_the_date(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    service.accept(db_session, _suggestion(db_session, K.CONFIRMATION, app).id, now=NOW)
    db_session.refresh(app)
    assert app.status == ApplicationStatus.APPLIED and app.date_applied == date(2026, 10, 8)
    assert _history(db_session, app) == []


def test_confirmation_keeps_an_existing_date(db_session):
    app = _app(db_session, ApplicationStatus.WISHLIST, date_applied=date(2026, 9, 1))
    service.accept(db_session, _suggestion(db_session, K.CONFIRMATION, app).id, now=NOW)
    db_session.refresh(app)
    assert app.date_applied == date(2026, 9, 1) and app.status == ApplicationStatus.APPLIED


@pytest.mark.parametrize(
    ("kind", "status"),
    [(K.REJECTION, ApplicationStatus.REJECTED), (K.OFFER, ApplicationStatus.OFFER)],
)
def test_rejection_and_offer_move_the_status(db_session, kind, status):
    app = _app(db_session, ApplicationStatus.INTERVIEW)
    result = service.accept(db_session, _suggestion(db_session, kind, app).id, now=NOW)
    db_session.refresh(app)
    assert app.status == status
    assert _history(db_session, app) == [(ApplicationStatus.INTERVIEW, status)]
    assert result.sheet_tabs == {TAB_APPLICATIONS}


def test_assessment_adds_a_note_and_a_follow_up(db_session):
    app = _app(db_session, notes="Referred by Sam")
    service.accept(db_session, _suggestion(db_session, K.ASSESSMENT, app).id, now=NOW)
    db_session.refresh(app)
    assert app.notes == "Referred by Sam\nOnline assessment received 2026-10-08"
    assert app.follow_up_date == date(2026, 10, 15)
    assert app.status == ApplicationStatus.APPLIED


def test_assessment_on_empty_notes(db_session):
    app = _app(db_session)
    service.accept(db_session, _suggestion(db_session, K.ASSESSMENT, app).id, now=NOW)
    db_session.refresh(app)
    assert app.notes == "Online assessment received 2026-10-08"


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("Phone screen with our recruiter", InterviewKind.RECRUITER_SCREEN),
        ("Technical interview invitation", InterviewKind.TECHNICAL),
        ("Interview invitation", InterviewKind.OTHER),
    ],
)
def test_interview_without_details_adds_a_round_of_the_suggested_kind(db_session, subject, kind):
    app = _app(db_session, ApplicationStatus.APPLIED)
    s = _suggestion(db_session, K.INTERVIEW, app, subject=subject)
    assert service.round_kind(s) == kind

    result = service.accept(db_session, s.id, now=NOW)

    (round_,) = db_session.scalars(select(InterviewRound).where(InterviewRound.application_id == app.id))
    assert round_.kind == kind and round_.scheduled_at is None and round_.state == InterviewState.SCHEDULED
    assert len(round_.checklist) == 6  # the default checklist
    db_session.refresh(app)
    assert app.status == ApplicationStatus.INTERVIEW
    assert result.sheet_tabs == {TAB_APPLICATIONS, *ROUND_SYNC_TABS}


def test_interview_with_the_add_round_form_fields(db_session):
    app = _app(db_session, ApplicationStatus.PHONE_SCREEN)
    when = datetime(2026, 10, 20, 17, tzinfo=UTC)
    data = AcceptIn(
        round=SuggestionRoundIn(
            application_id=999_999,  # ignored: the round goes to the suggestion's application
            kind=InterviewKind.TECHNICAL,
            title="Coding round",
            scheduled_at=when,
            duration_minutes=60,
        )
    )
    service.accept(db_session, _suggestion(db_session, K.INTERVIEW, app).id, data, now=NOW)

    (round_,) = db_session.scalars(select(InterviewRound).where(InterviewRound.application_id == app.id))
    assert (round_.kind, round_.title, round_.scheduled_at, round_.duration_minutes) == (
        InterviewKind.TECHNICAL,
        "Coding round",
        when,
        60,
    )
    db_session.refresh(app)
    assert app.status == ApplicationStatus.INTERVIEW and app.interview_datetime == when


def test_interview_does_not_move_a_later_status_back(db_session):
    app = _app(db_session, ApplicationStatus.INTERVIEW)
    service.accept(db_session, _suggestion(db_session, K.INTERVIEW, app).id, now=NOW)
    assert _history(db_session, app) == []


def test_contact_reply_marks_the_contact_replied_on_the_email_date(db_session):
    contact = _contact(db_session, ContactStatus.FOLLOWED_UP)
    result = service.accept(db_session, _suggestion(db_session, K.CONTACT_REPLY, contact=contact).id, now=NOW)
    db_session.refresh(contact)
    assert contact.status == ContactStatus.REPLIED and contact.replied_at == RECEIVED
    assert result.sheet_tabs == set(CONTACT_TABS)


def test_contact_sent_marks_the_contact_sent_on_the_email_date(db_session):
    contact = _contact(db_session, ContactStatus.TO_CONTACT)
    service.accept(db_session, _suggestion(db_session, K.CONTACT_SENT, contact=contact).id, now=NOW)
    db_session.refresh(contact)
    assert contact.status == ContactStatus.SENT and contact.sent_at == RECEIVED


def test_application_update_from_a_contact_also_marks_them_replied(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    contact = _contact(db_session, ContactStatus.SENT, application=app)
    result = service.accept(db_session, _suggestion(db_session, K.REJECTION, app, contact).id, now=NOW)
    db_session.refresh(app)
    db_session.refresh(contact)
    assert app.status == ApplicationStatus.REJECTED
    assert contact.status == ContactStatus.REPLIED and contact.replied_at == RECEIVED
    assert result.sheet_tabs == {TAB_APPLICATIONS, *CONTACT_TABS}


def test_application_update_from_a_contact_who_already_replied_leaves_them(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    contact = _contact(db_session, ContactStatus.MEETING, application=app)
    result = service.accept(db_session, _suggestion(db_session, K.OFFER, app, contact).id, now=NOW)
    db_session.refresh(contact)
    assert contact.status == ContactStatus.MEETING
    assert result.sheet_tabs == {TAB_APPLICATIONS}


def test_new_application_adds_it_as_applied(db_session):
    s = _suggestion(db_session, K.NEW_APPLICATION, proposed_company="Rivian", proposed_role="Software Intern")
    result = service.accept(db_session, s.id, now=NOW)

    app = db_session.get(Application, result.suggestion.application_id)
    assert (app.company, app.role_title, app.status, app.date_applied, app.source) == (
        "Rivian",
        "Software Intern",
        ApplicationStatus.APPLIED,
        date(2026, 10, 8),
        "Gmail",
    )
    assert _history(db_session, app) == [(None, ApplicationStatus.APPLIED)]
    assert result.sheet_tabs == {TAB_APPLICATIONS}


def test_new_application_with_edited_names_or_no_role(db_session):
    s = _suggestion(db_session, K.NEW_APPLICATION, proposed_company="Rivian")
    result = service.accept(db_session, s.id, AcceptIn(company=" Rivian Automotive ", role_title="ML Intern"), now=NOW)
    app = db_session.get(Application, result.suggestion.application_id)
    assert (app.company, app.role_title) == ("Rivian Automotive", "ML Intern")

    s = _suggestion(db_session, K.NEW_APPLICATION, proposed_company="Figma")
    app = db_session.get(Application, service.accept(db_session, s.id, now=NOW).suggestion.application_id)
    assert app.role_title == service.DEFAULT_ROLE


# --- stale -----------------------------------------------------------------------


STALE_CASES = [
    ("confirmation, already applied with a date", K.CONFIRMATION, dict(status=ApplicationStatus.APPLIED, date_applied=date(2026, 9, 1))),
    ("rejection, already rejected", K.REJECTION, dict(status=ApplicationStatus.REJECTED)),
    ("rejection after an offer", K.REJECTION, dict(status=ApplicationStatus.OFFER)),
    ("offer, already an offer", K.OFFER, dict(status=ApplicationStatus.OFFER)),
    ("interview, already rejected", K.INTERVIEW, dict(status=ApplicationStatus.REJECTED)),
    ("assessment, already rejected", K.ASSESSMENT, dict(status=ApplicationStatus.REJECTED)),
    ("archived application", K.REJECTION, dict(status=ApplicationStatus.APPLIED, archived=True)),
]


@pytest.mark.parametrize(("kind", "fields"), [c[1:] for c in STALE_CASES], ids=[c[0] for c in STALE_CASES])
def test_accepting_an_application_suggestion_that_no_longer_applies(db_session, kind, fields):
    app = _app(db_session, **fields)
    s = _suggestion(db_session, kind, app)
    with pytest.raises(SuggestionStaleError):
        service.accept(db_session, s.id, now=NOW)
    db_session.refresh(s)
    assert s.state == SuggestionState.STALE and s.decided_at == NOW
    assert _history(db_session, app) == []


def test_a_deleted_application_makes_its_suggestion_stale(db_session):
    app = _app(db_session)
    s = _suggestion(db_session, K.REJECTION, app)
    db_session.delete(app)
    db_session.commit()
    db_session.refresh(s)
    assert s.application_id is None and not service.is_valid(db_session, s)


@pytest.mark.parametrize(
    ("kind", "status", "archived"),
    [
        (K.CONTACT_REPLY, ContactStatus.REPLIED, False),
        (K.CONTACT_REPLY, ContactStatus.TO_CONTACT, False),
        (K.CONTACT_REPLY, ContactStatus.SENT, True),
        (K.CONTACT_SENT, ContactStatus.SENT, False),
    ],
)
def test_contact_suggestions_go_stale_when_the_contact_moved(db_session, kind, status, archived):
    contact = _contact(db_session, status, archived=archived)
    s = _suggestion(db_session, kind, contact=contact)
    with pytest.raises(SuggestionStaleError):
        service.accept(db_session, s.id, now=NOW)
    db_session.refresh(contact)
    assert contact.status == status


def test_new_application_goes_stale_once_the_company_is_tracked(db_session):
    s = _suggestion(db_session, K.NEW_APPLICATION, proposed_company="Rivian, Inc.")
    assert service.is_valid(db_session, s)
    _app(db_session, company="Rivian", archived=True)
    assert service.is_valid(db_session, s)  # an archived application doesn't count
    _app(db_session, company="Rivian")
    assert not service.is_valid(db_session, s)


def test_listing_marks_and_hides_stale_suggestions(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    keep = _suggestion(db_session, K.INTERVIEW, app)
    gone = _suggestion(db_session, K.REJECTION, app)
    app.status = ApplicationStatus.REJECTED  # moved by hand meanwhile
    db_session.commit()

    assert [s.id for s in service.list_suggestions(db_session, "pending", now=NOW)] == []
    db_session.refresh(keep)
    db_session.refresh(gone)
    assert keep.state == gone.state == SuggestionState.STALE
    assert service.list_suggestions(db_session, "all", now=NOW) == []


def test_pending_count_ignores_what_went_stale(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    _suggestion(db_session, K.REJECTION, app)
    _suggestion(db_session, K.OFFER, app)
    assert service.pending_count(db_session, NOW) == 2
    app.status = ApplicationStatus.OFFER
    db_session.commit()
    assert service.pending_count(db_session, NOW) == 0  # the rejection and the offer both no longer apply


# --- decisions -------------------------------------------------------------------


def test_dismiss_changes_nothing_but_the_suggestion(db_session):
    app = _app(db_session, ApplicationStatus.APPLIED)
    s = _suggestion(db_session, K.REJECTION, app)
    service.dismiss(db_session, s.id, now=NOW)
    db_session.refresh(app)
    assert s.state == SuggestionState.DISMISSED and s.decided_at == NOW
    assert app.status == ApplicationStatus.APPLIED


def test_a_decided_suggestion_cannot_be_decided_again(db_session):
    app = _app(db_session)
    s = _suggestion(db_session, K.ASSESSMENT, app)
    service.accept(db_session, s.id, now=NOW)
    with pytest.raises(SuggestionNotPendingError):
        service.accept(db_session, s.id, now=NOW)
    with pytest.raises(SuggestionNotPendingError):
        service.dismiss(db_session, s.id, now=NOW)


def test_unknown_suggestion(db_session):
    with pytest.raises(EmailSuggestionNotFoundError):
        service.accept(db_session, 999_999)
    with pytest.raises(EmailSuggestionNotFoundError):
        service.dismiss(db_session, 999_999)


def test_list_filters_and_order(db_session):
    app = _app(db_session)
    other = _app(db_session, company="Box")
    older = _suggestion(db_session, K.ASSESSMENT, app, received_at=RECEIVED - timedelta(days=2))
    newer = _suggestion(db_session, K.INTERVIEW, app)
    boxed = _suggestion(db_session, K.INTERVIEW, other, received_at=RECEIVED - timedelta(days=1))
    dismissed = _suggestion(db_session, K.OFFER, app, received_at=RECEIVED - timedelta(days=5))
    service.dismiss(db_session, dismissed.id, now=NOW)
    service.accept(db_session, older.id, now=NOW + timedelta(minutes=1))

    def ids(*args, **kwargs):
        return [s.id for s in service.list_suggestions(db_session, *args, now=NOW, **kwargs)]

    assert ids("pending") == [newer.id, boxed.id]
    assert ids("decided") == [older.id, dismissed.id]  # most recently decided first
    assert ids("all") == [newer.id, boxed.id, older.id, dismissed.id]
    assert ids("all", application_id=app.id) == [newer.id, older.id, dismissed.id]
    assert ids("pending", limit=1) == [newer.id]


# --- the sync's step for a new suggestion ------------------------------------------


def test_a_new_suggestion_that_already_does_not_apply_is_stale(db_session):
    app = _app(db_session, ApplicationStatus.REJECTED)
    s = _suggestion(db_session, K.REJECTION, app)
    assert service.on_new_suggestion(db_session, s, auto_apply=True, now=NOW) is None
    assert s.state == SuggestionState.STALE


@pytest.mark.parametrize("auto_apply", [False, True])
def test_a_contacts_stale_application_update_is_still_their_reply(db_session, auto_apply):
    """A rejection from a contact you emailed, for an application already
    rejected: the update no longer applies, but the reply does."""
    app = _app(db_session, ApplicationStatus.REJECTED)
    other = _app(db_session, company="Ramp")
    contact = _contact(db_session, ContactStatus.SENT, application=other)
    s = _suggestion(db_session, K.REJECTION, app, contact)

    result = service.on_new_suggestion(db_session, s, auto_apply=auto_apply, now=NOW)

    assert (s.kind, s.application_id, s.contact_id) == (K.CONTACT_REPLY, other.id, contact.id)
    db_session.refresh(contact)
    if auto_apply:
        assert result is not None and s.state == SuggestionState.AUTO_APPLIED
        assert contact.status == ContactStatus.REPLIED and contact.replied_at == RECEIVED
    else:
        assert result is None and s.state == SuggestionState.PENDING
        assert contact.status == ContactStatus.SENT
    db_session.refresh(app)
    assert app.status == ApplicationStatus.REJECTED


def test_a_stale_application_update_from_a_contact_who_already_replied_is_stale(db_session):
    app = _app(db_session, ApplicationStatus.REJECTED)
    contact = _contact(db_session, ContactStatus.REPLIED, application=app)
    s = _suggestion(db_session, K.REJECTION, app, contact)
    assert service.on_new_suggestion(db_session, s, auto_apply=True, now=NOW) is None
    assert (s.kind, s.state) == (K.REJECTION, SuggestionState.STALE)


@pytest.mark.parametrize("kind", [K.CONFIRMATION, K.CONTACT_REPLY, K.CONTACT_SENT])
def test_auto_apply_applies_the_safe_kinds(db_session, kind):
    app = _app(db_session, ApplicationStatus.WISHLIST)
    status = ContactStatus.TO_CONTACT if kind == K.CONTACT_SENT else ContactStatus.SENT
    contact = _contact(db_session, status) if kind != K.CONFIRMATION else None
    s = _suggestion(db_session, kind, app if kind == K.CONFIRMATION else None, contact)

    result = service.on_new_suggestion(db_session, s, auto_apply=True, now=NOW)

    assert result is not None and result.sheet_tabs
    assert s.state == SuggestionState.AUTO_APPLIED and s.decided_at == NOW


@pytest.mark.parametrize("kind", [K.REJECTION, K.INTERVIEW, K.ASSESSMENT, K.OFFER, K.NEW_APPLICATION])
def test_auto_apply_never_touches_the_other_kinds(db_session, kind):
    app = _app(db_session, ApplicationStatus.APPLIED) if kind != K.NEW_APPLICATION else None
    s = _suggestion(db_session, kind, app, proposed_company="Rivian" if app is None else None)
    assert service.on_new_suggestion(db_session, s, auto_apply=True, now=NOW) is None
    assert s.state == SuggestionState.PENDING
    if app is not None:
        db_session.refresh(app)
        assert app.status == ApplicationStatus.APPLIED


def test_without_auto_apply_safe_kinds_wait(db_session):
    app = _app(db_session, ApplicationStatus.WISHLIST)
    s = _suggestion(db_session, K.CONFIRMATION, app)
    assert service.on_new_suggestion(db_session, s, auto_apply=False, now=NOW) is None
    assert s.state == SuggestionState.PENDING


def test_gmail_url_is_built_from_the_thread_id():
    assert service.gmail_url("18c2f0a1") == "https://mail.google.com/mail/u/0/#all/18c2f0a1"
