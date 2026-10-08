"""Nudge computation (spec §13.4): a pure function of a contact's dates and
status, evaluated on read. No background job."""

import enum
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.models.contact import Contact, ContactStatus


class NudgeKind(str, enum.Enum):
    UNSENT = "unsent"
    FOLLOWUP_DUE = "followup_due"
    GONE_QUIET = "gone_quiet"
    REPLIED_STALE = "replied_stale"
    MEETING_OUTCOME = "meeting_outcome"


@dataclass(frozen=True)
class NudgeSettings:
    unsent_days: int
    followup_days: int
    gone_quiet_days: int
    replied_stale_days: int


def utc_today() -> date:
    """"Today" for nudges. Stored timestamps are compared by their UTC date,
    so today must be the UTC date too; the server's local date (TZ in
    docker-compose) would be a day off for part of every day."""
    return datetime.now(UTC).date()


def _older_than(moment: datetime | None, days: int, today: date) -> bool:
    return moment is not None and (today - moment.date()).days >= days


def compute_nudge(
    contact: Contact, last_status_change: datetime | None, settings: NudgeSettings, today: date
) -> NudgeKind | None:
    if contact.archived:
        return None
    if contact.nudge_snoozed_until is not None and today < contact.nudge_snoozed_until:
        return None
    status = contact.status
    if status == ContactStatus.TO_CONTACT and _older_than(contact.draft_ready_at, settings.unsent_days, today):
        return NudgeKind.UNSENT
    if status == ContactStatus.SENT and _older_than(contact.sent_at, settings.followup_days, today):
        return NudgeKind.FOLLOWUP_DUE
    if status == ContactStatus.FOLLOWED_UP and _older_than(
        contact.followed_up_at, settings.gone_quiet_days, today
    ):
        return NudgeKind.GONE_QUIET
    if status == ContactStatus.REPLIED and _older_than(
        last_status_change or contact.replied_at, settings.replied_stale_days, today
    ):
        return NudgeKind.REPLIED_STALE
    if status == ContactStatus.MEETING and contact.meeting_at is not None and contact.meeting_at.date() < today:
        return NudgeKind.MEETING_OUTCOME
    return None


def needs_followup_draft(contact: Contact, settings: NudgeSettings, today: date) -> bool:
    """True the day before "Follow-up due" appears, so the Claude job's draft
    is waiting when the user sees the nudge."""
    return (
        contact.status == ContactStatus.SENT
        and contact.followup_body is None
        and not contact.archived
        and _older_than(contact.sent_at, settings.followup_days - 1, today)
    )
