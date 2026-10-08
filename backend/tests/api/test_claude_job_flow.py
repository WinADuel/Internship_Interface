"""The daily Claude job's documented contract (ops/claude-routine/outreach-job.md),
walked end to end through the API with a real token."""

from datetime import UTC, datetime, timedelta

from app.models.contact import Contact, ContactKind, ContactStatus, EmailConfidence
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.services import contact_service
from app.services.claude_token_service import create_token
from app.services.contact_transitions import ContactAction


def test_claude_job_flow(logged_in_client, db_session):
    client = logged_in_client
    _, raw = create_token(db_session)
    bearer = {"Authorization": f"Bearer {raw}"}

    # 1. The user queues a professor and marks an application applied.
    r = client.post("/api/research-queue", json={"kind": "professor_person", "request_text": "Jane Lee, Stanford CS"})
    assert r.status_code == 201
    prof_item_id = r.json()["id"]
    r = client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE Intern", "status": "applied"})
    assert r.status_code == 201
    app_id = r.json()["id"]
    company_item = db_session.query(ResearchQueueItem).filter_by(application_id=app_id).one()
    assert company_item.kind == QueueKind.COMPANY_CONTACTS

    # 2. The job reads its work; the session cookie alone is not enough.
    assert client.get("/api/claude/work", headers={"Authorization": ""}).status_code == 401
    work = client.get("/api/claude/work", headers=bearer).json()
    queued = {q["id"]: q for q in work["queue"]}
    assert set(queued) == {prof_item_id, company_item.id}
    assert "Stripe" in queued[company_item.id]["request_text"]
    assert work["followups_needed"] == []

    # 3. It posts what it found, every fact backed by a source.
    r = client.post(
        "/api/claude/contacts",
        headers=bearer,
        json={
            "contacts": [
                {
                    "queue_item_id": prof_item_id,
                    "name": "Jane Lee",
                    "organization": "Stanford University",
                    "email": "jlee@stanford.edu",
                    "email_confidence": "found",
                    "research_summary": "Robot learning.",
                    "sources": [{"label": "Faculty page", "url": "https://cs.stanford.edu/~jlee"}],
                    "draft_subject": "Your robot learning work",
                    "draft_body": "Dear Professor Lee, ...",
                },
                {
                    "queue_item_id": company_item.id,
                    "name": "Sam Park",
                    "organization": "Stripe",
                    "title": "Engineering Manager",
                    "email": "spark@stripe.com",
                    "email_confidence": "pattern_guess",
                    "relevance_note": "Format inferred from jdoe@stripe.com on the press page.",
                    "sources": [{"label": "Team page", "url": "https://stripe.com/team"}],
                    "draft_subject": "SWE Intern application",
                    "draft_body": "Hi Sam, I applied to the SWE Intern role ...",
                },
            ]
        },
    )
    assert r.status_code == 200 and r.json() == {"created": 2, "updated": 0, "skipped": 0}

    # 4. It completes both items with a note on found vs. target.
    for item_id in (prof_item_id, company_item.id):
        r = client.post(f"/api/claude/queue/{item_id}/complete", headers=bearer, json={"result_note": "found 1 of 1"})
        assert r.status_code == 200 and r.json()["state"] == "done"
    assert client.get("/api/claude/work", headers=bearer).json()["queue"] == []

    # 5. The user sent the professor's email 9 days ago.
    prof = db_session.query(Contact).filter_by(kind=ContactKind.PROFESSOR).one()
    contact_service.apply_action(
        db_session, prof.id, ContactAction.SENT, on=datetime.now(UTC) - timedelta(days=9)
    )

    # 6. The next run sees a follow-up to draft.
    needed = client.get("/api/claude/work", headers=bearer).json()["followups_needed"]
    assert [f["contact_id"] for f in needed] == [prof.id]
    assert needed[0]["draft_subject"] == "Your robot learning work"

    # 7. It posts the follow-up.
    r = client.post(
        "/api/claude/followups",
        headers=bearer,
        json={"followups": [{"contact_id": prof.id, "followup_subject": "Re: Your robot learning work",
                             "followup_body": "Just following up on my note ..."}]},
    )
    assert r.status_code == 200 and r.json() == {"created": 0, "updated": 1, "skipped": 0}
    assert client.get("/api/claude/work", headers=bearer).json()["followups_needed"] == []

    # 8. Final state.
    db_session.expire_all()
    contacts = db_session.query(Contact).order_by(Contact.id).all()
    assert [(c.kind, c.name) for c in contacts] == [
        (ContactKind.PROFESSOR, "Jane Lee"),
        (ContactKind.COMPANY, "Sam Park"),
    ]
    prof, company = contacts
    assert prof.status == ContactStatus.SENT and prof.followup_body == "Just following up on my note ..."
    assert prof.email_confidence == EmailConfidence.FOUND
    assert company.application_id == app_id
    assert company.email_confidence == EmailConfidence.PATTERN_GUESS
    items = db_session.query(ResearchQueueItem).all()
    assert len(items) == 2 and {i.state for i in items} == {QueueState.DONE}
