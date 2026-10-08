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
        {"discovery_scan_hours": 0},
        {"discovery_scan_hours": 49},
        {"discovery_list_urls": ["http://example.com/listings.json"]},
        {"discovery_list_urls": ["ftp://example.com/listings.json"]},
        {"discovery_list_urls": ["https://"]},
        {"discovery_list_urls": ["https://example.com/" + "x" * 500]},
        {"discovery_list_urls": [f"https://example.com/{i}.json" for i in range(11)]},
        {"discovery_terms": ["x" * 101]},
        {"discovery_locations": [f"City {i}" for i in range(31)]},
        {"discovery_exclude_keywords": None},
        {"discovery_hide_no_sponsorship": None},
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
    # replied_at is backdated a year; the recent history row must win.
    apply_action(
        db_session, c.id, ContactAction.REPLIED, on=long_ago - timedelta(days=365), now=long_ago + timedelta(days=1)
    )
    result = list_needs_attention(db_session, today=date(2026, 1, 10))
    assert result == []
    result = list_needs_attention(db_session, today=date(2026, 1, 20))
    assert [(x.id, n) for x, n in result] == [(c.id, NudgeKind.REPLIED_STALE)]


def test_settings_update_normalizes_discovery_lists():
    data = SettingsUpdate(
        discovery_locations=[" Remote ", "remote", ""],
        discovery_exclude_keywords=["Senior", "  ", "staff", "SENIOR", "Staff "],
        discovery_list_urls=[" https://example.com/a.json ", "HTTPS://EXAMPLE.COM/A.JSON"],
    )
    assert data.discovery_locations == ["Remote"]
    assert data.discovery_exclude_keywords == ["Senior", "staff"]
    assert data.discovery_list_urls == ["https://example.com/a.json"]


def test_settings_update_list_limits_count_after_normalizing():
    # 31 raw items that collapse to one are fine; the cap is on distinct items.
    data = SettingsUpdate(discovery_terms=["Summer 2027"] * 31)
    assert data.discovery_terms == ["Summer 2027"]
    assert SettingsUpdate(discovery_terms=[]).discovery_terms == []


def test_update_settings_stores_discovery_fields(db_session):
    update_settings(
        db_session,
        SettingsUpdate(
            discovery_terms=["Summer 2028", "summer 2028"],
            discovery_scan_hours=12,
            discovery_hide_no_sponsorship=True,
        ),
    )
    s = get_settings(db_session)
    db_session.refresh(s)
    assert s.discovery_terms == ["Summer 2028"]
    assert (s.discovery_scan_hours, s.discovery_hide_no_sponsorship) == (12, True)
    assert s.discovery_categories == ["Software", "AI/ML/Data"]
