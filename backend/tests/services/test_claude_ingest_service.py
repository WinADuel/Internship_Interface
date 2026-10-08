from datetime import UTC, date, datetime, timedelta

from app.models.contact import Contact, ContactKind, ContactOrigin, ContactStatus, EmailConfidence
from app.models.research_queue import QueueState
from app.schemas.application import ApplicationCreate
from app.schemas.claude import ContactsBatchIn, FollowupsBatchIn
from app.schemas.contact import ContactCreate, ContactUpdate
from app.schemas.research_queue import QueueItemCreate
from app.schemas.settings import SettingsUpdate
from app.services.application_service import create_application
from app.services.claude_ingest_service import apply_followups, get_work, is_safe_url, upsert_contacts
from app.services.contact_service import apply_action, create_contact, update_contact
from app.services.contact_transitions import ContactAction
from app.services.research_queue_service import complete_item, enqueue_company_contacts, enqueue_professor
from app.services.settings_service import update_settings

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
SOURCE = {"label": "Faculty page", "url": "https://cs.stanford.edu/~jlee"}


def _prof_item(db, text="Jane Lee, Stanford"):
    return enqueue_professor(db, QueueItemCreate(kind="professor_person", request_text=text))


def _payload(item_id, **overrides):
    body = {
        "queue_item_id": item_id,
        "name": "Jane Lee",
        "organization": "Stanford",
        "email": "jlee@stanford.edu",
        "email_confidence": "found",
        "sources": [SOURCE],
        "research_summary": "Robotics",
        "draft_subject": "Hello",
        "draft_body": "Claude draft",
    }
    body.update(overrides)
    return body


def _ingest(db, *items, now=NOW):
    return upsert_contacts(db, ContactsBatchIn(contacts=list(items)), now=now)


def test_is_safe_url():
    assert is_safe_url("https://a.edu/x") and is_safe_url("HTTP://a.edu")
    for bad in [None, "", "javascript:alert(1)", "data:text/html,x", "ftp://a.edu", "https://", "//a.edu", "a.edu"]:
        assert not is_safe_url(bad), bad


def test_new_professor_contact_from_queue_item(db_session):
    item = _prof_item(db_session)
    result = _ingest(db_session, _payload(item.id))
    assert (result.created, result.updated, result.skipped) == (1, 0, 0)
    c = db_session.query(Contact).one()
    assert c.kind == ContactKind.PROFESSOR and c.application_id is None
    assert c.origin == ContactOrigin.CLAUDE and c.status == ContactStatus.TO_CONTACT
    assert c.draft_ready_at == NOW and c.email_confidence == EmailConfidence.FOUND
    assert c.sources == [SOURCE]


def test_new_company_contact_takes_kind_and_application_from_queue_item(db_session):
    app = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE Intern"))
    item = enqueue_company_contacts(db_session, app)
    _ingest(db_session, _payload(item.id, name="Sam", organization="Stripe", email="sam@stripe.com"))
    c = db_session.query(Contact).one()
    assert c.kind == ContactKind.COMPANY and c.application_id == app.id


def test_reingest_preserves_user_owned_fields_and_edited_draft(db_session):
    item = _prof_item(db_session)
    _ingest(db_session, _payload(item.id))
    c = db_session.query(Contact).one()
    update_contact(db_session, c.id, ContactUpdate(draft_body="my own words", notes="met at talk", priority="high"))
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    result = _ingest(
        db_session,
        _payload(item.id, draft_body="new Claude draft", research_summary="Updated summary", status="declined", notes="x"),
        now=NOW + timedelta(days=1),
    )
    assert (result.created, result.updated) == (0, 1)
    assert c.draft_body == "my own words" and c.status == ContactStatus.SENT
    assert c.notes == "met at talk" and c.priority.value == "high" and c.sent_at == NOW
    assert c.research_summary == "Updated summary" and c.origin == ContactOrigin.CLAUDE


def test_unedited_draft_is_refreshed(db_session):
    item = _prof_item(db_session)
    _ingest(db_session, _payload(item.id))
    _ingest(db_session, _payload(item.id, draft_subject="New subj", draft_body="Second draft"), now=NOW + timedelta(days=1))
    c = db_session.query(Contact).one()
    assert (c.draft_subject, c.draft_body) == ("New subj", "Second draft")
    assert c.draft_ready_at == NOW  # first delivery time is kept


def test_draft_ready_at_set_when_first_draft_arrives_on_match(db_session):
    item = _prof_item(db_session)
    _ingest(db_session, _payload(item.id, draft_subject=None, draft_body=None))
    c = db_session.query(Contact).one()
    assert c.draft_ready_at is None
    _ingest(db_session, _payload(item.id), now=NOW + timedelta(days=2))
    assert c.draft_ready_at == NOW + timedelta(days=2)


def test_reingest_without_fields_keeps_known_values(db_session):
    item = _prof_item(db_session)
    _ingest(db_session, _payload(item.id, title="Professor"))
    _ingest(db_session, _payload(item.id, email=None, email_confidence="not_found", sources=[], title=None))
    c = db_session.query(Contact).one()
    assert c.email == "jlee@stanford.edu" and c.email_confidence == EmailConfidence.FOUND
    assert c.sources == [SOURCE] and c.title == "Professor"


def test_dedup_by_email_case_insensitive_then_name_org(db_session):
    existing = create_contact(
        db_session, ContactCreate(kind="professor", name="J. Lee", organization="Stanford University", email="JLee@Stanford.edu")
    )
    other = create_contact(db_session, ContactCreate(kind="professor", name="Bob Ray", organization="MIT"))
    item = _prof_item(db_session)
    result = _ingest(
        db_session,
        _payload(item.id),  # email matches `existing` case-insensitively
        _payload(item.id, name="bob ray", organization="mit", email=None, email_confidence="not_found"),
        _payload(item.id, name="New Person", organization="CMU", email="np@cmu.edu"),
        _payload(item.id, name="new person", organization="cmu", email=None, email_confidence="not_found"),
    )
    assert (result.created, result.updated, result.skipped) == (1, 3, 0)
    assert existing.research_summary == "Robotics" and existing.origin == ContactOrigin.MANUAL
    assert existing.name == "J. Lee"  # identity is not research; left alone
    assert other.research_summary == "Robotics"
    assert db_session.query(Contact).count() == 3


def test_unsafe_urls_dropped(db_session):
    item = _prof_item(db_session)
    _ingest(
        db_session,
        _payload(
            item.id,
            website_url="javascript:alert(1)",
            profile_url="https://scholar.example.org/jlee",
            sources=[{"label": "x", "url": "data:text/html,<script>1</script>"}, {"label": "ok", "url": "https://cs.stanford.edu/~jlee"}],
        ),
    )
    c = db_session.query(Contact).one()
    assert c.website_url is None and c.profile_url == "https://scholar.example.org/jlee"
    assert c.sources == [{"label": "ok", "url": "https://cs.stanford.edu/~jlee"}]


def test_found_email_without_safe_source_downgraded(db_session):
    item = _prof_item(db_session)
    _ingest(db_session, _payload(item.id, sources=[{"label": "bad", "url": "javascript:void(0)"}]))
    c = db_session.query(Contact).one()
    assert c.email_confidence == EmailConfidence.PATTERN_GUESS and c.sources == []


def test_item_for_unknown_or_done_queue_item_skipped(db_session):
    done = _prof_item(db_session, "A")
    complete_item(db_session, done.id, "ok", now=NOW)
    result = _ingest(db_session, _payload(done.id), _payload(999999, name="Ghost"))
    assert (result.created, result.updated, result.skipped) == (0, 0, 2)
    assert db_session.query(Contact).count() == 0


def test_followup_not_applied_when_edited(db_session):
    a = create_contact(db_session, ContactCreate(kind="professor", name="A", organization="X"))
    b = create_contact(db_session, ContactCreate(kind="professor", name="B", organization="X"))
    update_contact(db_session, b.id, ContactUpdate(followup_body="mine"))
    result = apply_followups(
        db_session,
        FollowupsBatchIn(
            followups=[
                {"contact_id": a.id, "followup_subject": "Re: hi", "followup_body": "Following up"},
                {"contact_id": b.id, "followup_subject": "Re: hi", "followup_body": "Claude"},
                {"contact_id": 999999, "followup_subject": "s", "followup_body": "b"},
            ]
        ),
    )
    assert (result.updated, result.skipped) == (1, 2)
    assert (a.followup_subject, a.followup_body) == ("Re: hi", "Following up") and a.followup_edited is False
    assert b.followup_body == "mine"


def test_get_work_respects_max_items_and_lists_followups(db_session):
    update_settings(db_session, SettingsUpdate(claude_job_max_items=2, outreach_profile="CS junior"))
    items = [_prof_item(db_session, f"P{i}") for i in range(3)]
    due = create_contact(db_session, ContactCreate(kind="professor", name="Due", organization="MIT", email="d@mit.edu"))
    apply_action(db_session, due.id, ContactAction.SENT, on=NOW - timedelta(days=9), now=NOW)
    fresh = create_contact(db_session, ContactCreate(kind="professor", name="Fresh", organization="MIT"))
    apply_action(db_session, fresh.id, ContactAction.SENT, now=NOW)
    gone = create_contact(db_session, ContactCreate(kind="professor", name="Gone", organization="MIT"))
    gone.archived = True
    db_session.flush()
    work = get_work(db_session, today=NOW.date())
    assert [q["id"] for q in work["queue"]] == [items[0].id, items[1].id]
    assert work["outreach_profile"] == "CS junior"
    assert {k["name"] for k in work["known_contacts"]} == {"Due", "Fresh"}
    assert [f["contact_id"] for f in work["followups_needed"]] == [due.id]
