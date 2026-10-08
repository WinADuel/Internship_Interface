import pytest
from sqlalchemy.exc import IntegrityError

from app.models.app_settings import AppSettings
from app.models.application import Application, Priority
from app.models.claude_token import ClaudeToken
from app.models.contact import (
    Contact,
    ContactKind,
    ContactOrigin,
    ContactStatus,
    EmailConfidence,
)
from app.models.contact_status_history import ContactStatusHistory
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem


def test_contact_defaults(db_session):
    c = Contact(kind=ContactKind.PROFESSOR, name="Jane Lee", organization="Stanford")
    db_session.add(c)
    db_session.flush()
    assert c.status == ContactStatus.TO_CONTACT
    assert c.email_confidence == EmailConfidence.NOT_FOUND
    assert c.origin == ContactOrigin.MANUAL
    assert c.priority == Priority.MEDIUM
    assert c.draft_edited is False and c.followup_edited is False and c.archived is False
    assert c.sources == []


def test_contact_sources_server_default_is_empty_list(db_session):
    db_session.connection().exec_driver_sql(
        "INSERT INTO contacts (kind, name, organization, email_confidence, status, priority, origin)"
        " VALUES ('professor', 'Raw', 'MIT', 'not_found', 'to_contact', 'medium', 'manual')"
    )
    raw = db_session.connection().exec_driver_sql(
        "SELECT sources::text, draft_edited, archived FROM contacts WHERE name = 'Raw'"
    ).one()
    assert tuple(raw) == ("[]", False, False)


def test_contact_application_link_nulls_on_application_delete(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    c = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Stripe", application_id=app.id)
    db_session.add(c)
    db_session.flush()
    db_session.delete(app)
    db_session.flush()
    db_session.refresh(c)
    assert c.application_id is None


def test_contact_history_cascades_on_contact_delete(db_session):
    c = Contact(kind=ContactKind.PROFESSOR, name="Jane", organization="Stanford")
    db_session.add(c)
    db_session.flush()
    db_session.add(ContactStatusHistory(contact_id=c.id, old_status=None, new_status=ContactStatus.SENT))
    db_session.flush()
    db_session.connection().exec_driver_sql("DELETE FROM contacts WHERE id = %s", (c.id,))
    count = db_session.connection().exec_driver_sql(
        "SELECT count(*) FROM contact_status_history WHERE contact_id = %s", (c.id,)
    ).scalar_one()
    assert count == 0


def test_queue_item_and_settings_defaults(db_session):
    item = ResearchQueueItem(kind=QueueKind.PROFESSOR_PERSON, request_text="Jane Lee, Stanford")
    s = AppSettings(id=1)
    db_session.add_all([item, s])
    db_session.flush()
    assert item.state == QueueState.PENDING and item.target_count == 1
    assert (
        s.nudge_unsent_days,
        s.nudge_followup_days,
        s.nudge_gone_quiet_days,
        s.nudge_replied_stale_days,
    ) == (5, 10, 10, 14)
    assert s.claude_job_max_items == 8 and s.outreach_profile == ""
    assert s.backup_sheet_id is None and s.last_sheet_sync_at is None and s.last_sheet_sync_error is None


def test_claude_token_hash_is_unique(db_session):
    db_session.add(ClaudeToken(token_hash="a" * 64, token_prefix="ct_abcde"))
    db_session.flush()
    db_session.add(ClaudeToken(token_hash="a" * 64, token_prefix="ct_abcde"))
    with pytest.raises(IntegrityError):
        db_session.flush()
