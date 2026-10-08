"""The contact status-button table (spec §13.3) as data, shared by the
service layer and mirrored by the frontend."""

import enum
from datetime import timedelta

from app.models.contact import ContactStatus


class ContactAction(str, enum.Enum):
    SENT = "sent"
    FOLLOWED_UP = "followed_up"
    REPLIED = "replied"
    MEETING_SET = "meeting_set"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    NO_RESPONSE = "no_response"


ACTIONS_BY_STATUS: dict[ContactStatus, tuple[ContactAction, ...]] = {
    ContactStatus.TO_CONTACT: (ContactAction.SENT,),
    ContactStatus.SENT: (ContactAction.FOLLOWED_UP, ContactAction.REPLIED, ContactAction.DECLINED),
    ContactStatus.FOLLOWED_UP: (ContactAction.REPLIED, ContactAction.DECLINED, ContactAction.NO_RESPONSE),
    ContactStatus.REPLIED: (ContactAction.MEETING_SET, ContactAction.ACCEPTED, ContactAction.DECLINED),
    ContactStatus.MEETING: (ContactAction.ACCEPTED, ContactAction.DECLINED),
    ContactStatus.ACCEPTED: (),
    ContactStatus.DECLINED: (),
}

ACTION_RESULT: dict[ContactAction, ContactStatus] = {
    ContactAction.SENT: ContactStatus.SENT,
    ContactAction.FOLLOWED_UP: ContactStatus.FOLLOWED_UP,
    ContactAction.REPLIED: ContactStatus.REPLIED,
    ContactAction.MEETING_SET: ContactStatus.MEETING,
    ContactAction.ACCEPTED: ContactStatus.ACCEPTED,
    ContactAction.DECLINED: ContactStatus.DECLINED,
    ContactAction.NO_RESPONSE: ContactStatus.DECLINED,
}

ACTION_DATE_FIELD: dict[ContactAction, str] = {
    ContactAction.SENT: "sent_at",
    ContactAction.FOLLOWED_UP: "followed_up_at",
    ContactAction.REPLIED: "replied_at",
    ContactAction.MEETING_SET: "meeting_at",
}

# The date field stamped on entering a status; cleared again by undo.
STATUS_DATE_FIELD: dict[ContactStatus, str] = {
    ContactStatus.SENT: "sent_at",
    ContactStatus.FOLLOWED_UP: "followed_up_at",
    ContactStatus.REPLIED: "replied_at",
    ContactStatus.MEETING: "meeting_at",
}

NO_RESPONSE_REASON = "no_response"

UNDO_WINDOW = timedelta(seconds=60)
