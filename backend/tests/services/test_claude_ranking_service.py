"""The Claude routine's Inbox ranking step (Phase 5 spec §5, plan Task 3):
which postings it is given, what else it reads, and what it may write."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from pydantic import ValidationError

from app.models.posting import Posting, PostingSource, PostingState
from app.schemas.claude import MAX_CLAUDE_NOTE, MAX_SCORES, PostingScoresIn
from app.services import settings_service
from app.services.claude_ranking_service import EXAMPLES, ranking_work, save_scores

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
_seq = count()


def make(db, **overrides) -> Posting:
    n = next(_seq)
    values = {
        "source": PostingSource.SIMPLIFY,
        "source_key": f"cr{n}",
        "company": "Acme",
        "title": "Software Engineer Intern",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/c{n}",
        "url_key": f"https://jobs.example.com/c{n}",
        "terms": ["Summer 2027"],
        "category": "Software",
        "first_seen_at": NOW - timedelta(days=1),
        "last_seen_at": NOW,
        "state_changed_at": NOW - timedelta(days=1),
        "state": PostingState.NEW,
        "closed": False,
        "local_score": 50,
    }
    values.update(overrides)
    posting = Posting(**values)
    db.add(posting)
    db.flush()
    return posting


def settings(db, **values):
    s = settings_service.get_settings(db)
    for name, value in values.items():
        setattr(s, name, value)
    db.commit()
    return s


def work_ids(db) -> list[int]:
    return [p.id for p in ranking_work(db)["postings"]]


def scores(*items) -> PostingScoresIn:
    return PostingScoresIn(scores=[{"posting_id": i, "score": s, "note": n} for i, s, n in items])


# --- selection -----------------------------------------------------------------------


def test_postings_are_the_highest_local_scores_then_newest_up_to_the_daily_limit(db_session):
    db = db_session
    settings(db, ranking_claude_daily_limit=3)
    low = make(db, local_score=10)
    high = make(db, local_score=90)
    mid_old = make(db, local_score=60, date_posted=NOW - timedelta(days=5))
    mid_new = make(db, local_score=60, date_posted=NOW)
    make(db, local_score=None)
    assert work_ids(db) == [high.id, mid_new.id, mid_old.id]
    settings(db, ranking_claude_daily_limit=10)
    assert work_ids(db)[3] == low.id and len(work_ids(db)) == 5


def test_a_daily_limit_of_0_turns_claude_ranking_off(db_session):
    settings(db_session, ranking_claude_daily_limit=0)
    make(db_session)
    work = ranking_work(db_session)
    assert work["postings"] == []
    assert set(work) == {"profile", "preferences", "examples", "postings"}


def test_only_inbox_postings_passing_the_saved_filters_are_given(db_session):
    db = db_session
    settings(db, discovery_exclude_keywords=["senior"])
    shown = make(db)
    make(db, title="Senior Software Engineer")
    make(db, closed=True)
    make(db, state=PostingState.SAVED)
    make(db, state=PostingState.DISMISSED)
    make(db, state=PostingState.APPLIED)
    make(db, source=PostingSource.PASTED)
    assert work_ids(db) == [shown.id]


def test_postings_claude_already_scored_are_skipped_until_preferences_change(db_session):
    db = db_session
    changed = NOW - timedelta(days=1)
    settings(db, ranking_updated_at=None)
    scored = make(db, claude_score=80, claude_scored_at=changed - timedelta(hours=1))
    unscored = make(db)
    legacy = make(db, claude_score=70)  # a score with no time: reviewed again
    assert set(work_ids(db)) == {unscored.id, legacy.id}

    settings(db, ranking_updated_at=changed)  # stale now
    fresh = make(db, claude_score=60, claude_scored_at=changed + timedelta(hours=1))
    ids = set(work_ids(db))
    assert scored.id in ids and fresh.id not in ids


def test_payload_carries_profile_preferences_examples_and_posting_fields(db_session):
    db = db_session
    settings(
        db,
        outreach_profile="CS junior into ML infra.",
        ranking_role_keywords=["machine learning"],
        ranking_avoid_companies=["Initech"],
    )
    posting = make(
        db,
        company="Stripe",
        title="ML Infra Intern",
        locations=["New York, NY"],
        category="AI/ML/Data",
        date_posted=NOW,
        local_score=77,
        claude_note="kept private",
    )
    for i in range(EXAMPLES + 3):
        make(db, state=PostingState.SAVED, company=f"Saved {i}", title="Intern",
             state_changed_at=NOW - timedelta(minutes=i))
    make(db, state=PostingState.DISMISSED, company="Gone", title="Unpaid Intern")

    work = ranking_work(db)
    assert work["profile"] == "CS junior into ML infra."
    assert work["preferences"] == {
        "role_keywords": ["machine learning"],
        "skill_keywords": [],
        "preferred_locations": [],
        "preferred_companies": [],
        "avoid_companies": ["Initech"],
        "dealbreaker_keywords": [],
    }
    assert work["examples"]["saved"] == [f"Saved {i} — Intern" for i in range(EXAMPLES)]
    assert work["examples"]["dismissed"] == ["Gone — Unpaid Intern"]
    (given,) = work["postings"]
    assert given is posting


def test_applied_postings_are_positive_examples_with_saves_most_recent_first(db_session):
    db = db_session
    for i in range(EXAMPLES):
        make(db, state=PostingState.SAVED, company=f"Saved {i}", title="Intern",
             state_changed_at=NOW - timedelta(hours=2 * i + 1))
        make(db, state=PostingState.APPLIED, company=f"Applied {i}", title="Intern",
             state_changed_at=NOW - timedelta(hours=2 * i))

    saved = ranking_work(db)["examples"]["saved"]
    assert len(saved) == EXAMPLES
    assert saved[:4] == ["Applied 0 — Intern", "Saved 0 — Intern", "Applied 1 — Intern", "Saved 1 — Intern"]
    assert saved[-1] == f"Saved {EXAMPLES // 2 - 1} — Intern"


# --- writing scores ------------------------------------------------------------------


def test_scores_are_written_to_new_and_saved_postings_only(db_session):
    db = db_session
    new = make(db)
    saved = make(db, state=PostingState.SAVED)
    dismissed = make(db, state=PostingState.DISMISSED)
    applied = make(db, state=PostingState.APPLIED)

    result = save_scores(
        db,
        scores(
            (new.id, 88, "Strong fit: ML infra in Python; NYC"),
            (saved.id, 0, ""),
            (dismissed.id, 50, "x"),
            (applied.id, 50, "x"),
            (999999, 50, "x"),
        ),
        now=NOW,
    )
    assert (result.updated, result.skipped) == (2, 3)
    assert (new.claude_score, new.claude_note, new.claude_scored_at) == (88, "Strong fit: ML infra in Python; NYC", NOW)
    assert (saved.claude_score, saved.claude_note) == (0, None)
    assert dismissed.claude_score is None and applied.claude_score is None
    # Only the Claude columns change.
    assert new.state is PostingState.NEW and new.local_score == 50


def test_a_posting_listed_twice_takes_the_last_score(db_session):
    p = make(db_session)
    result = save_scores(db_session, scores((p.id, 10, "a"), (p.id, 90, "b")), now=NOW)
    assert (result.updated, result.skipped) == (2, 0)
    assert (p.claude_score, p.claude_note) == (90, "b")


def test_an_empty_batch_is_fine(db_session):
    assert save_scores(db_session, scores()).model_dump() == {"updated": 0, "skipped": 0}


def test_notes_are_cleaned_to_one_line_and_capped():
    batch = scores((1, 50, "  Good\x00 fit\n\tNYC\x1b[31m \u0085 ok "), (2, 50, "y" * 1000))
    assert batch.scores[0].note == "Good fit NYC [31m ok"
    assert batch.scores[1].note == "y" * MAX_CLAUDE_NOTE


def test_a_null_note_counts_as_no_note(db_session):
    # Like the other optional Claude fields, `"note": null` must not cost the
    # whole batch a 422 (found in the end-to-end check).
    batch = PostingScoresIn(scores=[{"posting_id": 1, "score": 50, "note": None}])
    assert batch.scores[0].note == ""
    p = make(db_session)
    save_scores(db_session, PostingScoresIn(scores=[{"posting_id": p.id, "score": 60, "note": None}]), now=NOW)
    assert (p.claude_score, p.claude_note) == (60, None)


@pytest.mark.parametrize(
    "payload",
    [
        {"scores": [{"posting_id": 1, "score": -1}]},
        {"scores": [{"posting_id": 1, "score": 101}]},
        {"scores": [{"posting_id": 1, "score": 50.5}]},
        {"scores": [{"posting_id": 1}]},
        {"scores": [{"score": 50}]},
        {"scores": [{"posting_id": 1, "score": 50, "note": "x" * (MAX_CLAUDE_NOTE * 10 + 1)}]},
        {"scores": [{"posting_id": i, "score": 50} for i in range(MAX_SCORES + 1)]},
    ],
)
def test_score_batches_are_validated(payload):
    with pytest.raises(ValidationError):
        PostingScoresIn(**payload)


def test_150_scores_is_allowed():
    assert MAX_SCORES == 150
    assert len(PostingScoresIn(scores=[{"posting_id": i, "score": 50} for i in range(150)]).scores) == 150
