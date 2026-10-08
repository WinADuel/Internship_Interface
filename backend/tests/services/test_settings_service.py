from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models.app_settings import AppSettings
from app.schemas.contact import ContactCreate
from app.schemas.settings import SettingsUpdate
from app.services.contact_service import apply_action, create_contact, list_needs_attention
from app.services.contact_transitions import ContactAction
from app.services.nudges import NudgeKind, NudgeSettings
from app.services.settings_service import get_settings, nudge_settings, update_settings


def test_get_settings_creates_defaults_once(db_session):
    s1 = get_settings(db_session)
    s2 = get_settings(db_session)
    assert s1 is s2 and s1.id == 1
    assert db_session.scalar(select(func.count()).select_from(AppSettings)) == 1
    assert nudge_settings(s1) == NudgeSettings(5, 10, 10, 14)


def test_update_settings_changes_only_supplied_fields(db_session):
    update_settings(db_session, SettingsUpdate(nudge_followup_days=7, outreach_profile="CS junior"))
    s = get_settings(db_session)
    assert (s.nudge_followup_days, s.outreach_profile) == (7, "CS junior")
    assert (s.nudge_unsent_days, s.claude_job_max_items) == (5, 8)


@pytest.mark.parametrize(
    "payload",
    [
        {"nudge_followup_days": 0},
        {"nudge_unsent_days": 91},
        {"claude_job_max_items": 26},
        {"outreach_profile": "x" * 5001},
        {"nudge_gone_quiet_days": None},
    ],
)
def test_settings_update_validation(payload):
    with pytest.raises(ValidationError):
        SettingsUpdate(**payload)


def test_list_needs_attention_returns_only_due_contacts(db_session):
    now = datetime.now(UTC)
    due = create_contact(db_session, ContactCreate(kind="professor", name="Due", organization="MIT"))
    fresh = create_contact(db_session, ContactCreate(kind="professor", name="Fresh", organization="MIT"))
    apply_action(db_session, due.id, ContactAction.SENT, on=now - timedelta(days=11), now=now)
    apply_action(db_session, fresh.id, ContactAction.SENT, on=now - timedelta(days=2), now=now)
    result = list_needs_attention(db_session, today=now.date())
    assert [(c.id, n) for c, n in result] == [(due.id, NudgeKind.FOLLOWUP_DUE)]


def test_list_needs_attention_replied_stale_uses_history(db_session):
    long_ago = datetime(2026, 1, 1, tzinfo=UTC)
    c = create_contact(db_session, ContactCreate(kind="professor", name="Old", organization="MIT"))
    apply_action(db_session, c.id, ContactAction.SENT, now=long_ago)
    apply_action(db_session, c.id, ContactAction.REPLIED, now=long_ago + timedelta(days=1))
    result = list_needs_attention(db_session, today=date(2026, 1, 10))
    assert result == []
    result = list_needs_attention(db_session, today=date(2026, 1, 20))
    assert [(x.id, n) for x, n in result] == [(c.id, NudgeKind.REPLIED_STALE)]
