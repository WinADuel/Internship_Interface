import pytest

from app.schemas.settings import SettingsUpdate

from app.models.contact import Contact
from app.services.claude_token_service import create_token


@pytest.fixture()
def claude(client, db_session):
    _, raw = create_token(db_session)
    client.headers["Authorization"] = f"Bearer {raw}"
    return client


def _queue_prof(db_session):
    from app.schemas.research_queue import QueueItemCreate
    from app.services.research_queue_service import enqueue_professor

    return enqueue_professor(db_session, QueueItemCreate(kind="professor_person", request_text="Jane Lee"))


def _contact(item_id, i=0, **kw):
    return {"queue_item_id": item_id, "name": f"P{i}", "organization": "MIT", "email_confidence": "not_found", **kw}


def test_work_shape(claude):
    body = claude.get("/api/claude/work").json()
    assert set(body) == {"queue", "outreach_profile", "known_contacts", "followups_needed"}


def test_oversized_batch_is_422_and_writes_nothing(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, i) for i in range(26)]})
    assert r.status_code == 422
    assert db_session.query(Contact).count() == 0


def test_oversized_field_is_422(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, research_summary="x" * 5001)]})
    assert r.status_code == 422
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, sources=[{"label": "a", "url": "https://a.b"}] * 21)]})
    assert r.status_code == 422
    assert db_session.query(Contact).count() == 0


def test_valid_batch_upserts(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post("/api/claude/contacts", json={"contacts": [_contact(item.id, 1), _contact(item.id, 2)]})
    assert r.status_code == 200 and r.json() == {"created": 2, "updated": 0, "skipped": 0}


def test_followups_route(claude, db_session):
    c = Contact(kind="professor", name="A", organization="X", status="sent")
    db_session.add(c)
    db_session.flush()
    r = claude.post(
        "/api/claude/followups",
        json={"followups": [{"contact_id": c.id, "followup_subject": "Re", "followup_body": "Hi again"}]},
    )
    assert r.status_code == 200 and r.json() == {"created": 0, "updated": 1, "skipped": 0}


def test_complete_then_complete_again_409(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post(f"/api/claude/queue/{item.id}/complete", json={"result_note": "found 1 of 1"})
    assert r.status_code == 200 and r.json()["state"] == "done" and r.json()["result_note"] == "found 1 of 1"
    r = claude.post(f"/api/claude/queue/{item.id}/complete", json={"result_note": "again"})
    assert r.status_code == 409 and r.json() == {"detail": "queue item not pending"}
    r = claude.post("/api/claude/queue/999999/failed", json={"result_note": "x"})
    assert r.status_code == 404 and r.json() == {"detail": "queue item not found"}


def test_failed_route(claude, db_session):
    item = _queue_prof(db_session)
    r = claude.post(f"/api/claude/queue/{item.id}/failed", json={"result_note": "could not identify"})
    assert r.status_code == 200 and r.json()["state"] == "failed"


# --- Discover Inbox ranking (Phase 5 spec §5) ----------------------------------


def _posting(db_session, key="1", **kw):
    from app.models.posting import Posting, PostingSource, PostingState

    values = dict(
        source=PostingSource.SIMPLIFY,
        source_key=key,
        company="Acme",
        title="ML Intern",
        locations=["New York, NY"],
        url=f"https://jobs.example.com/{key}",
        url_key=f"https://jobs.example.com/{key}",
        terms=["Summer 2027"],
        category="AI/ML/Data",
        state=PostingState.NEW,
        local_score=64,
    )
    values.update(kw)
    p = Posting(**values)
    db_session.add(p)
    db_session.flush()
    return p


def test_ranking_work_shape(claude, db_session):
    p = _posting(db_session)
    body = claude.get("/api/claude/postings").json()
    assert set(body) == {"profile", "preferences", "preferences_as_of", "examples", "postings"}
    assert body["preferences_as_of"] is None
    assert body["examples"] == {"saved": [], "dismissed": []}
    assert set(body["preferences"]) == {
        "role_keywords", "skill_keywords", "preferred_locations",
        "preferred_companies", "avoid_companies", "dealbreaker_keywords",
    }
    assert body["postings"] == [
        {
            "id": p.id,
            "company": "Acme",
            "title": "ML Intern",
            "locations": ["New York, NY"],
            "url": "https://jobs.example.com/1",
            "category": "AI/ML/Data",
            "terms": ["Summer 2027"],
            "date_posted": None,
            "local_score": 64,
        }
    ]


def test_scores_route_writes_and_counts(claude, db_session):
    from app.models.posting import PostingState

    new = _posting(db_session, "1")
    dismissed = _posting(db_session, "2", state=PostingState.DISMISSED)
    r = claude.post(
        "/api/claude/postings/scores",
        json={"scores": [
            {"posting_id": new.id, "score": 91, "note": "Strong fit: ML infra in Python; NYC; posted today"},
            {"posting_id": dismissed.id, "score": 10, "note": "No"},
        ]},
    )
    assert r.status_code == 200 and r.json() == {"updated": 1, "skipped": 1}
    db_session.refresh(new)
    assert new.claude_score == 91 and new.claude_scored_at is not None
    # Scored postings are not handed out again.
    assert [p["id"] for p in claude.get("/api/claude/postings").json()["postings"]] == []


def test_scores_echo_preferences_as_of_and_read_stale_after_a_change(claude, db_session):
    from app.services import settings_service

    p = _posting(db_session)
    settings_service.update_settings(db_session, SettingsUpdate(ranking_role_keywords=["ml"]))
    as_of = claude.get("/api/claude/postings").json()["preferences_as_of"]
    assert as_of is not None

    # Echoed unchanged with no change in between: fresh, not offered again.
    r = claude.post(
        "/api/claude/postings/scores",
        json={"preferences_as_of": as_of, "scores": [{"posting_id": p.id, "score": 91}]},
    )
    assert r.status_code == 200 and r.json() == {"updated": 1, "skipped": 0}
    assert claude.get("/api/claude/postings").json()["postings"] == []

    # The user changes the preferences while the routine is scoring: what it
    # sends back was made against the old ones, so it reads stale.
    settings_service.update_settings(db_session, SettingsUpdate(ranking_role_keywords=["ai"]))
    r = claude.post(
        "/api/claude/postings/scores",
        json={"preferences_as_of": as_of, "scores": [{"posting_id": p.id, "score": 93}]},
    )
    assert r.json() == {"updated": 1, "skipped": 0}
    db_session.refresh(p)
    assert p.claude_score == 93
    assert [q["id"] for q in claude.get("/api/claude/postings").json()["postings"]] == [p.id]


def test_oversized_score_batch_is_422_and_writes_nothing(claude, db_session):
    p = _posting(db_session)
    r = claude.post("/api/claude/postings/scores", json={"scores": [{"posting_id": p.id, "score": 50}] * 151})
    assert r.status_code == 422
    r = claude.post("/api/claude/postings/scores", json={"scores": [{"posting_id": p.id, "score": 101}]})
    assert r.status_code == 422
    db_session.refresh(p)
    assert p.claude_score is None
