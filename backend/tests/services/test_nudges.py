from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.contact import Contact, ContactKind, ContactStatus
from app.services.nudges import NudgeKind, NudgeSettings, compute_nudge, needs_followup_draft

TODAY = date(2026, 10, 20)
S = NudgeSettings(5, 10, 10, 14)


def _days_ago(n: int) -> datetime:
    return datetime(2026, 10, 20, 9, 0, tzinfo=UTC) - timedelta(days=n)


def _contact(status: str, **fields) -> Contact:
    return Contact(kind=ContactKind.PROFESSOR, name="Jane", organization="Stanford", status=ContactStatus(status), **fields)


@pytest.mark.parametrize(
    "status,field,days_ago,expected",
    [
        ("to_contact", "draft_ready_at", 5, NudgeKind.UNSENT),
        ("to_contact", "draft_ready_at", 4, None),
        ("sent", "sent_at", 10, NudgeKind.FOLLOWUP_DUE),
        ("sent", "sent_at", 9, None),
        ("followed_up", "followed_up_at", 10, NudgeKind.GONE_QUIET),
        ("followed_up", "followed_up_at", 9, None),
    ],
)
def test_date_threshold_nudges(status, field, days_ago, expected):
    c = _contact(status, **{field: _days_ago(days_ago)})
    assert compute_nudge(c, None, S, TODAY) == expected


def test_replied_stale_uses_last_status_change():
    c = _contact("replied", replied_at=_days_ago(30))
    assert compute_nudge(c, _days_ago(14), S, TODAY) == NudgeKind.REPLIED_STALE
    assert compute_nudge(c, _days_ago(13), S, TODAY) is None


def test_replied_stale_falls_back_to_replied_at():
    assert compute_nudge(_contact("replied", replied_at=_days_ago(14)), None, S, TODAY) == NudgeKind.REPLIED_STALE
    assert compute_nudge(_contact("replied", replied_at=_days_ago(13)), None, S, TODAY) is None


def test_meeting_outcome_after_meeting_day():
    assert compute_nudge(_contact("meeting", meeting_at=_days_ago(1)), None, S, TODAY) == NudgeKind.MEETING_OUTCOME
    assert compute_nudge(_contact("meeting", meeting_at=_days_ago(0)), None, S, TODAY) is None


def test_snooze_hides_nudge_until_date():
    c = _contact("sent", sent_at=_days_ago(12), nudge_snoozed_until=TODAY + timedelta(days=1))
    assert compute_nudge(c, None, S, TODAY) is None
    c.nudge_snoozed_until = TODAY
    assert compute_nudge(c, None, S, TODAY) == NudgeKind.FOLLOWUP_DUE


def test_archived_contact_has_no_nudge():
    c = _contact("sent", sent_at=_days_ago(12), archived=True)
    assert compute_nudge(c, None, S, TODAY) is None


def test_to_contact_without_draft_has_no_nudge():
    assert compute_nudge(_contact("to_contact"), None, S, TODAY) is None


def test_closed_contacts_have_no_nudge():
    assert compute_nudge(_contact("accepted"), _days_ago(100), S, TODAY) is None
    assert compute_nudge(_contact("declined"), _days_ago(100), S, TODAY) is None


def test_needs_followup_draft_one_day_early():
    assert needs_followup_draft(_contact("sent", sent_at=_days_ago(9)), S, TODAY) is True
    assert needs_followup_draft(_contact("sent", sent_at=_days_ago(9), followup_body="hi"), S, TODAY) is False
    assert needs_followup_draft(_contact("sent", sent_at=_days_ago(8)), S, TODAY) is False
    assert needs_followup_draft(_contact("sent", sent_at=_days_ago(9), archived=True), S, TODAY) is False
    assert needs_followup_draft(_contact("followed_up", sent_at=_days_ago(20)), S, TODAY) is False
