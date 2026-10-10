from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models.application import Application
from app.models.contact import Contact, ContactKind
from app.models.interview import (
    InterviewKind,
    InterviewOutcome,
    InterviewRound,
    InterviewState,
    interview_round_contacts,
)
from app.models.story import Story
from app.schemas.interview import InterviewRoundCreate, InterviewRoundUpdate
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    ContactNotOnApplicationError,
    InterviewRoundNotFoundError,
    StoryArchivedError,
    StoryNotFoundError,
)
from app.services.interview_service import (
    DEFAULT_CHECKLIST,
    checklist_progress,
    create_round,
    delete_round,
    get_round,
    list_rounds,
    set_round_contacts,
    set_round_stories,
    thank_you_due,
    update_round,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _app(db, company="Acme") -> Application:
    application = Application(company=company, role_title="SWE Intern")
    db.add(application)
    db.flush()
    return application


def _round(db, application, **fields) -> InterviewRound:
    return create_round(db, InterviewRoundCreate(application_id=application.id, **fields))


def _contact(db, application_id=None, name="Pat Doe") -> Contact:
    contact = Contact(kind=ContactKind.COMPANY, name=name, organization="Acme", application_id=application_id)
    db.add(contact)
    db.flush()
    return contact


# --- create / defaults -------------------------------------------------------


def test_new_round_gets_defaults_and_default_checklist(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application)
    assert interview_round.kind == InterviewKind.OTHER
    assert interview_round.state == InterviewState.SCHEDULED
    assert [item["label"] for item in interview_round.checklist] == list(DEFAULT_CHECKLIST)
    assert all(item["done"] is False for item in interview_round.checklist)
    ids = [item["id"] for item in interview_round.checklist]
    assert all(ids) and len(set(ids)) == len(ids)
    assert interview_round.created_at is not None


def test_supplied_checklist_replaces_default_and_missing_ids_are_assigned(db_session):
    application = _app(db_session)
    interview_round = _round(
        db_session, application, checklist=[{"label": "  Print resume ", "done": True}, {"id": "k", "label": "B"}]
    )
    assert interview_round.checklist[0]["label"] == "Print resume"
    assert interview_round.checklist[0]["done"] is True
    assert interview_round.checklist[0]["id"]
    assert interview_round.checklist[1] == {"id": "k", "label": "B", "done": False}


def test_create_round_for_missing_application_raises(db_session):
    with pytest.raises(ApplicationNotFoundError):
        create_round(db_session, InterviewRoundCreate(application_id=999_999))


def test_get_round_raises_when_missing(db_session):
    with pytest.raises(InterviewRoundNotFoundError):
        get_round(db_session, 999_999)


# --- derived interview_datetime ----------------------------------------------


def test_interview_datetime_is_earliest_scheduled_round(db_session):
    application = _app(db_session)
    later = _round(db_session, application, scheduled_at=NOW + timedelta(days=5))
    assert application.interview_datetime == NOW + timedelta(days=5)
    earlier = _round(db_session, application, scheduled_at=NOW + timedelta(days=2))
    _round(db_session, application)  # no date: ignored
    assert application.interview_datetime == NOW + timedelta(days=2)

    update_round(db_session, earlier.id, InterviewRoundUpdate(state=InterviewState.DONE))
    assert application.interview_datetime == NOW + timedelta(days=5)

    update_round(db_session, later.id, InterviewRoundUpdate(scheduled_at=NOW + timedelta(days=9)))
    assert application.interview_datetime == NOW + timedelta(days=9)

    delete_round(db_session, later.id)
    assert application.interview_datetime is None


def test_cancelled_rounds_do_not_count(db_session):
    application = _app(db_session)
    _round(db_session, application, scheduled_at=NOW, state=InterviewState.CANCELLED)
    assert application.interview_datetime is None


def test_rounds_of_other_applications_do_not_count(db_session):
    mine, other = _app(db_session), _app(db_session, "Other")
    _round(db_session, other, scheduled_at=NOW)
    assert mine.interview_datetime is None
    assert other.interview_datetime == NOW


# --- update / delete ---------------------------------------------------------


def test_update_sets_given_fields_only(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application, title="Screen", prep_notes="keep")
    update_round(
        db_session,
        interview_round.id,
        InterviewRoundUpdate(
            title="Coding round 2", outcome=InterviewOutcome.PASSED, checklist=[{"id": "a", "label": "Only"}]
        ),
    )
    assert interview_round.title == "Coding round 2"
    assert interview_round.outcome == InterviewOutcome.PASSED
    assert interview_round.prep_notes == "keep"
    assert interview_round.checklist == [{"id": "a", "label": "Only", "done": False}]


def test_update_missing_round_raises(db_session):
    with pytest.raises(InterviewRoundNotFoundError):
        update_round(db_session, 999_999, InterviewRoundUpdate(title="x"))


def test_delete_round_removes_it_and_its_links(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application)
    set_round_contacts(db_session, interview_round.id, [_contact(db_session).id])
    delete_round(db_session, interview_round.id)
    assert db_session.get(InterviewRound, interview_round.id) is None
    assert db_session.execute(select(interview_round_contacts)).all() == []


def test_deleting_application_cascades_to_rounds(db_session):
    application = _app(db_session)
    round_id = _round(db_session, application).id
    db_session.delete(application)
    db_session.flush()
    db_session.expunge_all()
    assert db_session.get(InterviewRound, round_id) is None


# --- validation caps ---------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "x" * 201},
        {"duration_minutes": 4},
        {"duration_minutes": 601},
        {"location": "x" * 501},
        {"interviewers": "x" * 501},
        {"prep_notes": "x" * 20_001},
        {"reflection": "x" * 20_001},
        {"questions_to_ask": "x" * 5_001},
        {"checklist": [{"label": f"item {i}"} for i in range(31)]},
        {"checklist": [{"label": "x" * 201}]},
        {"checklist": [{"label": "   "}]},
        {"checklist": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]},
        {"scheduled_at": "2026-10-10T09:00:00"},  # no timezone
    ],
)
def test_round_input_caps(fields):
    with pytest.raises(ValidationError):
        InterviewRoundCreate(application_id=1, **fields)
    with pytest.raises(ValidationError):
        InterviewRoundUpdate(**fields)


def test_round_caps_allow_the_limits():
    InterviewRoundCreate(
        application_id=1,
        title="x" * 200,
        duration_minutes=600,
        prep_notes="x" * 20_000,
        questions_to_ask="x" * 5_000,
        checklist=[{"label": "x" * 200} for _ in range(30)],
    )


@pytest.mark.parametrize("field", ["kind", "state", "checklist"])
def test_update_rejects_null_for_non_nullable_fields(field):
    with pytest.raises(ValidationError):
        InterviewRoundUpdate(**{field: None})


# --- listing -----------------------------------------------------------------


def test_list_scopes_and_order(db_session):
    application = _app(db_session)
    soon = _round(db_session, application, scheduled_at=NOW + timedelta(days=1))
    later = _round(db_session, application, scheduled_at=NOW + timedelta(days=3))
    undated = _round(db_session, application)
    missed = _round(db_session, application, scheduled_at=NOW - timedelta(days=1))  # still "scheduled"
    done = _round(db_session, application, scheduled_at=NOW - timedelta(days=4), state=InterviewState.DONE)
    cancelled_future = _round(
        db_session, application, scheduled_at=NOW + timedelta(days=2), state=InterviewState.CANCELLED
    )

    upcoming = list_rounds(db_session, "upcoming", now=NOW)
    assert [r.id for r in upcoming] == [soon.id, later.id, undated.id]
    past = list_rounds(db_session, "past", now=NOW)
    assert [r.id for r in past] == [cancelled_future.id, missed.id, done.id]
    everything = list_rounds(db_session, now=NOW)
    assert [r.id for r in everything] == [done.id, missed.id, soon.id, cancelled_future.id, later.id, undated.id]


def test_list_filters_by_application(db_session):
    mine, other = _app(db_session), _app(db_session, "Other")
    kept = _round(db_session, mine)
    _round(db_session, other)
    assert [r.id for r in list_rounds(db_session, application_id=mine.id)] == [kept.id]


def test_lists_hide_archived_applications_except_their_own_list(db_session):
    live, archived = _app(db_session), _app(db_session, "Gone")
    archived.archived = True
    shown = _round(db_session, live, scheduled_at=NOW + timedelta(days=1))
    hidden = _round(db_session, archived, scheduled_at=NOW + timedelta(days=1))
    hidden_past = _round(db_session, archived, scheduled_at=NOW - timedelta(days=1), state=InterviewState.DONE)
    for scope in ("upcoming", "past", "all"):
        ids = {r.id for r in list_rounds(db_session, scope, now=NOW)}
        assert hidden.id not in ids and hidden_past.id not in ids
    assert [r.id for r in list_rounds(db_session, "upcoming", now=NOW)] == [shown.id]
    assert [r.id for r in list_rounds(db_session, application_id=archived.id, now=NOW)] == [
        hidden_past.id,
        hidden.id,
    ]
    assert list_rounds(db_session, now=NOW)[0].application.company == "Acme"


# --- contact links -----------------------------------------------------------


def test_link_contacts_links_unattached_contact_to_the_application(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application)
    own = _contact(db_session, application.id, "Own")
    loose = _contact(db_session, None, "Loose")
    set_round_contacts(db_session, interview_round.id, [loose.id, own.id, loose.id])
    assert [c.id for c in interview_round.contacts] == sorted([own.id, loose.id])
    assert loose.application_id == application.id


def test_link_contact_of_another_application_is_rejected(db_session):
    application, other = _app(db_session), _app(db_session, "Other")
    interview_round = _round(db_session, application)
    foreign = _contact(db_session, other.id)
    loose = _contact(db_session, None, "Loose")
    with pytest.raises(ContactNotOnApplicationError):
        set_round_contacts(db_session, interview_round.id, [loose.id, foreign.id])
    assert foreign.application_id == other.id
    assert loose.application_id is None  # nothing changed


def test_link_missing_contact_raises(db_session):
    interview_round = _round(db_session, _app(db_session))
    with pytest.raises(ContactNotFoundError):
        set_round_contacts(db_session, interview_round.id, [999_999])


def test_set_contacts_replaces_the_set(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application)
    a, b = _contact(db_session, application.id, "A"), _contact(db_session, application.id, "B")
    set_round_contacts(db_session, interview_round.id, [a.id, b.id])
    set_round_contacts(db_session, interview_round.id, [b.id])
    assert [c.id for c in interview_round.contacts] == [b.id]
    set_round_contacts(db_session, interview_round.id, [])
    assert interview_round.contacts == []


def test_deleting_a_contact_unlinks_it(db_session):
    application = _app(db_session)
    interview_round = _round(db_session, application)
    contact = _contact(db_session, application.id)
    set_round_contacts(db_session, interview_round.id, [contact.id])
    db_session.delete(contact)
    db_session.commit()
    db_session.expire_all()
    assert interview_round.contacts == []


# --- story links -------------------------------------------------------------


def test_set_stories_replaces_the_set(db_session):
    interview_round = _round(db_session, _app(db_session))
    a, b = Story(title="A"), Story(title="B")
    db_session.add_all([a, b])
    db_session.flush()
    set_round_stories(db_session, interview_round.id, [b.id, a.id])
    assert [s.id for s in interview_round.stories] == [a.id, b.id]
    set_round_stories(db_session, interview_round.id, [a.id])
    assert [s.id for s in interview_round.stories] == [a.id]


def test_archived_story_stays_linked_but_cannot_be_newly_linked(db_session):
    interview_round = _round(db_session, _app(db_session))
    kept, other = Story(title="Kept"), Story(title="Other", archived=True)
    db_session.add_all([kept, other])
    db_session.flush()
    set_round_stories(db_session, interview_round.id, [kept.id])
    kept.archived = True
    db_session.flush()
    set_round_stories(db_session, interview_round.id, [kept.id])  # already linked: fine
    assert [s.id for s in interview_round.stories] == [kept.id]
    with pytest.raises(StoryArchivedError):
        set_round_stories(db_session, interview_round.id, [kept.id, other.id])
    assert [s.id for s in interview_round.stories] == [kept.id]


def test_link_missing_story_raises(db_session):
    interview_round = _round(db_session, _app(db_session))
    with pytest.raises(StoryNotFoundError):
        set_round_stories(db_session, interview_round.id, [999_999])


# --- thank-you due and checklist progress ------------------------------------


def _bare_round(**fields) -> InterviewRound:
    defaults = {"state": InterviewState.DONE, "scheduled_at": NOW - timedelta(hours=2), "thank_you_sent_at": None}
    return InterviewRound(**{**defaults, **fields})


def test_thank_you_due_for_a_recent_done_round():
    assert thank_you_due(_bare_round(), NOW) is True


@pytest.mark.parametrize(
    "fields",
    [
        {"state": InterviewState.SCHEDULED},
        {"state": InterviewState.CANCELLED},
        {"thank_you_sent_at": NOW - timedelta(hours=1)},
        {"scheduled_at": None},
        {"scheduled_at": NOW - timedelta(days=3, seconds=1)},
    ],
)
def test_thank_you_not_due(fields):
    assert thank_you_due(_bare_round(**fields), NOW) is False


def test_thank_you_due_until_exactly_three_days():
    assert thank_you_due(_bare_round(scheduled_at=NOW - timedelta(days=3)), NOW) is True


def test_checklist_progress():
    interview_round = InterviewRound(
        checklist=[{"id": "a", "label": "A", "done": True}, {"id": "b", "label": "B", "done": False}]
    )
    assert checklist_progress(interview_round) == (1, 2)
    assert checklist_progress(InterviewRound(checklist=[])) == (0, 0)
