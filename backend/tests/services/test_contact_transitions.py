from app.models.contact import ContactStatus
from app.services.contact_transitions import (
    ACTION_DATE_FIELD,
    ACTION_RESULT,
    ACTIONS_BY_STATUS,
    UNDO_WINDOW,
    ContactAction,
)


def test_actions_by_status_matches_spec_table():
    assert ACTIONS_BY_STATUS == {
        ContactStatus.TO_CONTACT: (ContactAction.SENT,),
        ContactStatus.SENT: (ContactAction.FOLLOWED_UP, ContactAction.REPLIED, ContactAction.DECLINED),
        ContactStatus.FOLLOWED_UP: (ContactAction.REPLIED, ContactAction.DECLINED, ContactAction.NO_RESPONSE),
        ContactStatus.REPLIED: (ContactAction.MEETING_SET, ContactAction.ACCEPTED, ContactAction.DECLINED),
        ContactStatus.MEETING: (ContactAction.ACCEPTED, ContactAction.DECLINED),
        ContactStatus.ACCEPTED: (),
        ContactStatus.DECLINED: (),
    }


def test_action_results_and_date_fields():
    assert ACTION_RESULT[ContactAction.NO_RESPONSE] == ContactStatus.DECLINED
    assert ACTION_RESULT[ContactAction.MEETING_SET] == ContactStatus.MEETING
    assert ACTION_RESULT[ContactAction.SENT] == ContactStatus.SENT
    assert ACTION_DATE_FIELD == {
        ContactAction.SENT: "sent_at",
        ContactAction.FOLLOWED_UP: "followed_up_at",
        ContactAction.REPLIED: "replied_at",
        ContactAction.MEETING_SET: "meeting_at",
    }
    assert UNDO_WINDOW.total_seconds() == 60
