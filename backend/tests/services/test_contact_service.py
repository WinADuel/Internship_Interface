from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.contact import ContactKind, ContactStatus
from app.schemas.application import ApplicationCreate
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.application_service import create_application
from app.services.contact_service import (
    apply_action,
    archive_contact,
    create_contact,
    get_contact,
    get_contact_history,
    get_recent_contact_activity,
    list_contacts,
    move_status,
    snooze_contact,
    undo_last_action,
    update_contact,
)
from app.services.contact_transitions import ContactAction
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    InvalidTransitionError,
    UndoExpiredError,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _jane(db):
    return create_contact(db, ContactCreate(kind="professor", name="Jane", organization="Stanford"))


def _at_status(db, *actions):
    c = _jane(db)
    t = NOW - timedelta(hours=len(actions))
    for action in actions:
        kwargs = {"meeting_at": NOW + timedelta(days=2)} if action == ContactAction.MEETING_SET else {}
        apply_action(db, c.id, action, now=t, **kwargs)
        t += timedelta(hours=1)
    return c


def test_create_and_get_contact(db_session):
    c = _jane(db_session)
    assert get_contact(db_session, c.id).name == "Jane"
    assert c.origin.value == "manual"


def test_get_missing_contact_raises(db_session):
    with pytest.raises(ContactNotFoundError):
        get_contact(db_session, 999999)


def test_create_with_unknown_application_raises(db_session):
    with pytest.raises(ApplicationNotFoundError):
        create_contact(
            db_session, ContactCreate(kind="company", name="Sam", organization="Stripe", application_id=999999)
        )


def test_list_contacts_filters(db_session):
    app = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE Intern"))
    prof = _jane(db_session)
    comp = create_contact(
        db_session, ContactCreate(kind="company", name="Sam", organization="Stripe", application_id=app.id)
    )
    gone = create_contact(db_session, ContactCreate(kind="company", name="Old", organization="X"))
    archive_contact(db_session, gone.id)
    assert {c.id for c in list_contacts(db_session)} == {prof.id, comp.id}
    assert [c.id for c in list_contacts(db_session, kind=ContactKind.PROFESSOR)] == [prof.id]
    assert [c.id for c in list_contacts(db_session, application_id=app.id)] == [comp.id]
    assert len(list_contacts(db_session, include_archived=True)) == 3


def test_sent_action_stamps_date_and_writes_history(db_session):
    c = _jane(db_session)
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    assert c.status == ContactStatus.SENT and c.sent_at == NOW
    [h] = get_contact_history(db_session, c.id)
    assert (h.old_status, h.new_status) == (ContactStatus.TO_CONTACT, ContactStatus.SENT)


def test_backdated_action_uses_on(db_session):
    c = _jane(db_session)
    apply_action(db_session, c.id, ContactAction.SENT, on=NOW - timedelta(days=3), now=NOW)
    assert c.sent_at == NOW - timedelta(days=3)


def test_invalid_action_raises_and_writes_nothing(db_session):
    c = _jane(db_session)
    with pytest.raises(InvalidTransitionError):
        apply_action(db_session, c.id, ContactAction.ACCEPTED, now=NOW)
    assert c.status == ContactStatus.TO_CONTACT and get_contact_history(db_session, c.id) == []


def test_meeting_set_requires_meeting_at(db_session):
    c = _at_status(db_session, ContactAction.SENT, ContactAction.REPLIED)
    with pytest.raises(InvalidTransitionError):
        apply_action(db_session, c.id, ContactAction.MEETING_SET, now=NOW)
    assert c.status == ContactStatus.REPLIED and len(get_contact_history(db_session, c.id)) == 2
    meeting = NOW + timedelta(days=3)
    apply_action(db_session, c.id, ContactAction.MEETING_SET, meeting_at=meeting, now=NOW)
    assert c.status == ContactStatus.MEETING and c.meeting_at == meeting


def test_no_response_closes_as_declined_with_reason(db_session):
    c = _at_status(db_session, ContactAction.SENT, ContactAction.FOLLOWED_UP)
    apply_action(db_session, c.id, ContactAction.NO_RESPONSE, now=NOW)
    assert c.status == ContactStatus.DECLINED and c.closed_reason == "no_response"


def test_move_status_follows_transition_rules(db_session):
    c = _jane(db_session)
    move_status(db_session, c.id, ContactStatus.SENT, now=NOW)
    assert c.status == ContactStatus.SENT and c.sent_at == NOW


def test_move_status_rejects_skipping_stages(db_session):
    c = _jane(db_session)
    with pytest.raises(InvalidTransitionError):
        move_status(db_session, c.id, ContactStatus.REPLIED, now=NOW)
    assert c.status == ContactStatus.TO_CONTACT


def test_move_status_rejects_meeting(db_session):
    c = _at_status(db_session, ContactAction.SENT, ContactAction.REPLIED)
    with pytest.raises(InvalidTransitionError):
        move_status(db_session, c.id, ContactStatus.MEETING, now=NOW)


def test_undo_within_window_restores_previous_state(db_session):
    c = _jane(db_session)
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    undo_last_action(db_session, c.id, now=NOW + timedelta(seconds=59))
    assert c.status == ContactStatus.TO_CONTACT and c.sent_at is None
    assert get_contact_history(db_session, c.id) == []


def test_undo_no_response_clears_reason(db_session):
    c = _at_status(db_session, ContactAction.SENT, ContactAction.FOLLOWED_UP)
    apply_action(db_session, c.id, ContactAction.NO_RESPONSE, now=NOW)
    undo_last_action(db_session, c.id, now=NOW + timedelta(seconds=5))
    assert c.status == ContactStatus.FOLLOWED_UP and c.closed_reason is None
    assert c.followed_up_at is not None


def test_undo_after_window_raises(db_session):
    c = _jane(db_session)
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    with pytest.raises(UndoExpiredError):
        undo_last_action(db_session, c.id, now=NOW + timedelta(seconds=61))
    assert c.status == ContactStatus.SENT


def test_undo_without_history_raises(db_session):
    c = _jane(db_session)
    with pytest.raises(UndoExpiredError):
        undo_last_action(db_session, c.id, now=NOW)


def test_editing_draft_marks_it_edited(db_session):
    c = _jane(db_session)
    update_contact(db_session, c.id, ContactUpdate(draft_body="my words"))
    assert c.draft_edited is True and c.followup_edited is False
    update_contact(db_session, c.id, ContactUpdate(followup_subject="Re: hi"))
    assert c.followup_edited is True


def test_update_other_fields_does_not_mark_drafts_edited(db_session):
    c = _jane(db_session)
    update_contact(db_session, c.id, ContactUpdate(notes="met at talk", priority="high"))
    assert c.notes == "met at talk" and c.priority.value == "high"
    assert c.draft_edited is False and c.followup_edited is False


def test_action_clears_snooze(db_session):
    c = _jane(db_session)
    snooze_contact(db_session, c.id, 3, today=date(2026, 10, 6))
    assert c.nudge_snoozed_until == date(2026, 10, 9)
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    assert c.nudge_snoozed_until is None


def test_history_oldest_first_and_recent_activity_newest_first(db_session):
    c = _at_status(db_session, ContactAction.SENT, ContactAction.REPLIED)
    history = get_contact_history(db_session, c.id)
    assert [h.new_status for h in history] == [ContactStatus.SENT, ContactStatus.REPLIED]
    activity = get_recent_contact_activity(db_session, limit=1)
    assert activity == [
        {
            "contact_id": c.id,
            "name": "Jane",
            "organization": "Stanford",
            "kind": ContactKind.PROFESSOR,
            "old_status": ContactStatus.SENT,
            "new_status": ContactStatus.REPLIED,
            "changed_at": history[1].changed_at,
        }
    ]
