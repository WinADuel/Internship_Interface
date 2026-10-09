"""The Inbox's local match score (Phase 5 spec §3-§4, plan Task 1): the pure
scoring rules, then storing scores (ingest, actions, preference changes, the
daily scan pass) against the test database. No network."""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from sqlalchemy import insert, select

from app.models.app_settings import AppSettings
from app.models.posting import Posting, PostingSource, PostingState
from app.schemas.discovery import PasteConfirmIn
from app.schemas.settings import SettingsUpdate
from app.services import settings_service
from app.services.discovery import actions
from app.services.discovery.ingest import ingest
from app.services.discovery.ranking import (
    MAX_REASON_LENGTH,
    MAX_REASONS,
    NEUTRAL_SCORE,
    LocalScore,
    Ranker,
    RankingPrefs,
    prefs_from_settings,
    rescore,
    score_posting,
)
from tests.services.discovery.test_ingest import pin, result

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=60)  # earns no freshness points


@dataclass
class Facts:
    title: str = "Software Engineer Intern"
    company: str = "Acme"
    locations: list[str] = field(default_factory=lambda: ["Boston, MA"])
    category: str | None = "Software"
    date_posted: datetime | None = OLD
    first_seen_at: datetime = OLD
    watch_company_id: int | None = None


def score(prefs: RankingPrefs, **facts) -> LocalScore:
    return score_posting(Facts(**facts), prefs, NOW)


def roles(*words: str) -> RankingPrefs:
    return RankingPrefs(role_keywords=words)


# --- no preferences ----------------------------------------------------------------


def test_no_preferences_scores_everything_neutral_without_reasons():
    assert score(RankingPrefs(), date_posted=NOW) == LocalScore(NEUTRAL_SCORE, [])
    assert score(RankingPrefs(), date_posted=OLD) == LocalScore(50, [])
    assert RankingPrefs().empty and RankingPrefs(role_keywords=["  ", ""]).empty


def test_prefs_are_cleaned_and_compare_by_value():
    prefs = RankingPrefs(role_keywords=[" machine  learning ", "Machine Learning", "backend", ""])
    assert prefs.role_keywords == ("machine learning", "backend")
    assert prefs == RankingPrefs(role_keywords=("machine learning", "backend"))
    assert not prefs.empty


def test_prefs_from_settings_reads_the_ranking_columns():
    s = AppSettings(
        ranking_role_keywords=["ml"],
        ranking_skill_keywords=["python"],
        ranking_preferred_locations=["New York"],
        ranking_preferred_companies=["Stripe"],
        ranking_avoid_companies=["Initech"],
        ranking_dealbreaker_keywords=["unpaid"],
    )
    assert prefs_from_settings(s) == RankingPrefs(
        role_keywords=("ml",),
        skill_keywords=("python",),
        preferred_locations=("New York",),
        preferred_companies=("Stripe",),
        avoid_companies=("Initech",),
        dealbreaker_keywords=("unpaid",),
    )


# --- role keywords -----------------------------------------------------------------


def test_one_role_keyword_in_the_title_is_40():
    assert score(roles("machine learning"), title="Machine Learning Intern") == LocalScore(
        40, ["Title matches 'machine learning'"]
    )


def test_each_extra_role_keyword_adds_5_up_to_50():
    title = "Backend Infrastructure Machine Learning Platform Intern"
    assert score(roles("backend", "infrastructure"), title=title).score == 45
    assert score(roles("backend", "infrastructure", "machine learning"), title=title).score == 50
    four = score(roles("backend", "infrastructure", "machine learning", "platform"), title=title)
    assert four.score == 50
    assert four.reasons == ["Title matches 'backend', 'infrastructure', 'machine learning', 'platform'"]


def test_role_keywords_match_whole_words_ignoring_case():
    prefs = roles("ml")
    assert score(prefs, title="ML Engineer Intern").score == 40
    assert score(prefs, title="Intern, ml/infra").score == 40
    assert score(prefs, title="HTML Developer Intern").score == 0
    assert score(prefs, title="Mlops Intern").score == 0


@pytest.mark.parametrize(
    ("keyword", "title", "expected"),
    [
        ("c++", "C++ Developer Intern", 40),
        ("c++", "C Developer Intern", 0),
        (".net", "Intern (.NET)", 40),
        ("a.b", "axb Intern", 0),
        ("(x", "Intern (x team", 40),
    ],
)
def test_role_keywords_with_regex_metacharacters_match_literally(keyword, title, expected):
    assert score(roles(keyword), title=title).score == expected


def test_role_keywords_only_look_at_the_title():
    assert score(roles("software"), title="Data Intern", category="Software").score == 0


# --- skill keywords ----------------------------------------------------------------


def test_skill_keywords_in_title_or_category_are_5_each_up_to_15():
    prefs = RankingPrefs(skill_keywords=("python", "pytorch", "distributed", "go"))
    assert score(prefs, title="Python Intern").reasons == ["Skills: python"]
    assert score(prefs, title="Python Intern").score == 5
    assert score(prefs, title="Python PyTorch Intern").score == 10
    assert score(prefs, title="Intern", category="AI/ML/Data").score == 0
    assert score(RankingPrefs(skill_keywords=("data",)), title="Intern", category="AI/ML/Data").score == 5
    full = score(prefs, title="Distributed Python PyTorch Go Intern")
    assert full.score == 15
    assert full.reasons == ["Skills: python, pytorch, distributed, go"]
    # Whole words: "go" is not in "Google".
    assert score(prefs, title="Google Intern").score == 0


# --- location ----------------------------------------------------------------------


def test_a_preferred_location_substring_of_any_location_is_15():
    prefs = RankingPrefs(preferred_locations=("New York", "Chicago"))
    hit = score(prefs, locations=["Boston, MA", "New York, NY"])
    assert hit == LocalScore(15, ["New York"])
    assert score(prefs, locations=["new york city"]).score == 15
    assert score(prefs, locations=["Boston, MA"]).score == 0
    assert score(prefs, locations=[]).score == 0
    # Counted once, however many match.
    assert score(prefs, locations=["Chicago, IL", "New York, NY"]).score == 15


def test_remote_also_matches_remote_anywhere_in_the_title():
    prefs = RankingPrefs(preferred_locations=("Remote",))
    assert score(prefs, locations=["Remote in USA"]).score == 15
    assert score(prefs, locations=[], title="Software Intern (Remote)") == LocalScore(15, ["Remote"])
    assert score(RankingPrefs(preferred_locations=("Boston",)), locations=[], title="Boston Intern").score == 0


# --- company -----------------------------------------------------------------------


def test_a_preferred_company_is_15_matching_whole_words():
    prefs = RankingPrefs(preferred_companies=("Stripe",))
    assert score(prefs, company="Stripe") == LocalScore(15, ["Preferred company"])
    assert score(prefs, company="stripe, Inc.").score == 15
    assert score(prefs, company="Stripes Apparel").score == 0


def test_a_watchlist_company_posting_is_15_and_does_not_stack_with_preferred():
    prefs = RankingPrefs(preferred_companies=("Stripe",))
    assert score(prefs, company="Acme", watch_company_id=3) == LocalScore(15, ["Watchlist company"])
    assert score(prefs, company="Stripe", watch_company_id=3) == LocalScore(15, ["Preferred company"])


# --- freshness ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("age", "points", "reason"),
    [
        (timedelta(0), 10, "posted today"),
        (timedelta(hours=-5), 10, "posted today"),  # a date a little in the future
        (timedelta(days=1), 10, "posted 1 day ago"),
        (timedelta(days=3), 10, "posted 3 days ago"),
        (timedelta(days=3, seconds=1), 6, "posted 3 days ago"),
        (timedelta(days=7), 6, "posted 7 days ago"),
        (timedelta(days=7, seconds=1), 3, "posted 7 days ago"),
        (timedelta(days=14), 3, "posted 14 days ago"),
        (timedelta(days=14, seconds=1), 0, None),
    ],
)
def test_freshness_boundaries(age, points, reason):
    prefs = roles("nothing-matches-this")
    got = score(prefs, date_posted=NOW - age)
    assert got.score == points
    assert got.reasons == ([reason] if reason else [])


def test_freshness_falls_back_to_first_seen_when_there_is_no_posted_date():
    prefs = roles("nothing-matches-this")
    assert score(prefs, date_posted=None, first_seen_at=NOW - timedelta(days=2)).score == 10
    assert score(prefs, date_posted=OLD, first_seen_at=NOW).score == 0


def test_every_signal_together_is_capped_at_100():
    prefs = RankingPrefs(
        role_keywords=("machine learning", "infrastructure", "backend"),
        skill_keywords=("python", "pytorch", "distributed"),
        preferred_locations=("New York",),
        preferred_companies=("Stripe",),
    )
    got = score(
        prefs,
        title="Backend Infrastructure Machine Learning Intern (Python, PyTorch, Distributed)",
        company="Stripe",
        locations=["New York, NY"],
        date_posted=NOW - timedelta(days=1),
    )
    assert got.score == 100
    assert got.reasons == [
        "Title matches 'machine learning', 'infrastructure', 'backend'",
        "Skills: python, pytorch, distributed",
        "New York",
        "Preferred company",
        "posted 1 day ago",
    ]


# --- overrides ---------------------------------------------------------------------


def test_a_dealbreaker_in_the_title_scores_0_with_the_reason():
    prefs = RankingPrefs(role_keywords=("software",), dealbreaker_keywords=("unpaid", "clearance"))
    got = score(prefs, title="Unpaid Software Intern", date_posted=NOW)
    assert got == LocalScore(0, ["Dealbreaker: 'unpaid'"])
    assert score(prefs, title="Software Intern (Clearance Required)").reasons == ["Dealbreaker: 'clearance'"]
    # Whole words only.
    assert score(prefs, title="Software Intern (unpaidish)").score == 40


def test_an_avoided_company_scores_0():
    prefs = RankingPrefs(role_keywords=("software",), avoid_companies=("Initech",))
    assert score(prefs, company="Initech LLC") == LocalScore(0, ["Avoided company"])
    both = score(
        RankingPrefs(avoid_companies=("Initech",), dealbreaker_keywords=("unpaid",)),
        company="Initech",
        title="Unpaid Intern",
    )
    assert both == LocalScore(0, ["Dealbreaker: 'unpaid'", "Avoided company"])


def test_dealbreakers_alone_still_score_freshness_for_the_rest():
    prefs = RankingPrefs(dealbreaker_keywords=("unpaid",))
    assert score(prefs, date_posted=NOW).score == 10


def test_reasons_are_capped_in_number_and_length():
    long_words = tuple(f"{'x' * 55}{i}" for i in range(30))
    got = score(RankingPrefs(role_keywords=long_words), title=" ".join(long_words))
    assert got.score == 50
    assert len(got.reasons) <= MAX_REASONS
    assert all(len(r) <= MAX_REASON_LENGTH for r in got.reasons)


# --- storing scores ----------------------------------------------------------------

_seq = count()


def make(db, **overrides) -> Posting:
    n = next(_seq)
    values = {
        "source": PostingSource.SIMPLIFY,
        "source_key": f"rk{n}",
        "company": "Acme",
        "title": "Software Engineer Intern",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/r{n}",
        "url_key": f"https://jobs.example.com/r{n}",
        "terms": ["Summer 2027"],
        "category": "Software",
        "first_seen_at": OLD,
        "last_seen_at": NOW,
        "state_changed_at": OLD,
        "state": PostingState.NEW,
        "closed": False,
    }
    values.update(overrides)
    posting = Posting(**values)
    db.add(posting)
    db.flush()
    return posting


def set_prefs(db, **prefs) -> AppSettings:
    s = settings_service.get_settings(db)
    for name, value in prefs.items():
        setattr(s, f"ranking_{name}", list(value))
    db.commit()
    return s


def test_ingest_scores_inserted_and_updated_rows_with_the_saved_preferences(db_session):
    db = db_session
    set_prefs(db, role_keywords=["backend"])
    ingest(db, result([pin("a", title="Backend Intern"), pin("b", title="Frontend Intern")]), NOW)
    rows = {p.source_key: p for p in db.scalars(select(Posting))}
    assert (rows["a"].local_score, rows["a"].local_reasons) == (50, ["Title matches 'backend'", "posted today"])
    assert (rows["b"].local_score, rows["b"].local_reasons) == (10, ["posted today"])

    # A later scan re-scores the rows it updates (here with an explicit ranker).
    later = NOW + timedelta(days=5)
    ingest(db, result([pin("a", title="Backend Intern"), pin("b", title="Frontend Intern")]), later,
           ranker=Ranker(roles("frontend")))
    db.expire_all()
    rows = {p.source_key: p for p in db.scalars(select(Posting))}
    assert (rows["a"].local_score, rows["b"].local_score) == (6, 46)


def test_ingest_with_no_preferences_scores_neutral(db_session):
    ingest(db_session, result([pin("a")]), NOW)
    (row,) = db_session.scalars(select(Posting))
    assert (row.local_score, row.local_reasons) == (50, [])


def test_changing_preferences_rescores_new_and_saved_postings_only(db_session):
    db = db_session
    new = make(db, title="Backend Intern", local_score=50)
    saved = make(db, title="Backend Intern", state=PostingState.SAVED, local_score=50)
    dismissed = make(db, title="Backend Intern", state=PostingState.DISMISSED, local_score=50)
    applied = make(db, title="Backend Intern", state=PostingState.APPLIED, local_score=50)
    other = make(db, title="Frontend Intern", local_score=50)
    db.commit()

    s = settings_service.update_settings(db, SettingsUpdate(ranking_role_keywords=["backend"]), now=NOW)
    assert s.ranking_updated_at == NOW
    assert (new.local_score, new.local_reasons) == (40, ["Title matches 'backend'"])
    assert saved.local_score == 40
    assert other.local_score == 0 and other.local_reasons == []
    assert dismissed.local_score == 50 and applied.local_score == 50


def test_unchanged_preferences_do_not_stamp_or_rescore(db_session):
    db = db_session
    settings_service.update_settings(db, SettingsUpdate(ranking_role_keywords=["backend"]), now=NOW)
    p = make(db, title="Backend Intern", local_score=77)
    db.commit()
    later = NOW + timedelta(hours=1)
    s = settings_service.update_settings(
        db,
        SettingsUpdate(ranking_role_keywords=["backend"], ranking_claude_daily_limit=10, nudge_unsent_days=6),
        now=later,
    )
    assert s.ranking_updated_at == NOW
    assert s.ranking_claude_daily_limit == 10
    assert p.local_score == 77


def test_clearing_every_preference_goes_back_to_neutral(db_session):
    db = db_session
    settings_service.update_settings(db, SettingsUpdate(ranking_role_keywords=["backend"]), now=NOW)
    p = make(db, title="Backend Intern", local_score=40)
    db.commit()
    settings_service.update_settings(db, SettingsUpdate(ranking_role_keywords=[]), now=NOW)
    assert (p.local_score, p.local_reasons) == (50, [])


def test_restoring_or_saving_a_dismissed_posting_rescores_it(db_session):
    db = db_session
    set_prefs(db, role_keywords=["backend"])
    a = make(db, title="Backend Intern", state=PostingState.DISMISSED, local_score=3)
    b = make(db, title="Backend Intern", state=PostingState.DISMISSED, local_score=3)
    db.commit()
    assert actions.restore(db, a.id, now=NOW).local_score == 40
    assert actions.save(db, b.id, now=NOW).local_score == 40


def test_pasted_postings_are_scored(db_session):
    db = db_session
    set_prefs(db, role_keywords=["backend"])
    posting = actions.paste_confirm(
        db,
        PasteConfirmIn(url="https://example.com/jobs/1", company="Acme", title="Backend Intern"),
        now=NOW,
    )
    assert (posting.local_score, posting.local_reasons) == (50, ["Title matches 'backend'", "posted today"])


def test_rescore_skips_rows_whose_score_is_unchanged(db_session):
    db = db_session
    make(db, title="Backend Intern", local_score=40, local_reasons=["Title matches 'backend'"])
    stale = make(db, title="Backend Intern", local_score=1)
    assert rescore(db, roles("backend"), NOW) == 1
    assert stale.local_score == 40


def test_rescoring_5000_postings_takes_a_second_or_two(db_session):
    """Spec §8: re-scoring a real-size Inbox is fast enough to run inline on
    a preferences change. The measured time is printed (-s shows it)."""
    db = db_session
    rows = [
        {
            "source": PostingSource.SIMPLIFY,
            "source_key": f"bulk{i}",
            "company": f"Company {i % 700}",
            "title": ("Machine Learning Intern" if i % 5 == 0 else "Software Engineer Intern")
            + (" (Python)" if i % 3 == 0 else ""),
            "locations": ["New York, NY", "Remote"] if i % 4 == 0 else ["Austin, TX"],
            "url": f"https://jobs.example.com/bulk/{i}",
            "url_key": f"https://jobs.example.com/bulk/{i}",
            "terms": ["Summer 2027"],
            "category": "AI/ML/Data" if i % 5 == 0 else "Software",
            "date_posted": NOW - timedelta(hours=i % 400),
            "state": PostingState.SAVED if i % 50 == 0 else PostingState.NEW,
            "local_score": NEUTRAL_SCORE,
        }
        for i in range(5000)
    ]
    db.execute(insert(Posting), rows)
    db.commit()

    started = time.perf_counter()
    settings_service.update_settings(
        db,
        SettingsUpdate(
            ranking_role_keywords=["machine learning", "backend", "infrastructure"],
            ranking_skill_keywords=["python", "pytorch", "distributed"],
            ranking_preferred_locations=["New York", "Remote", "Chicago"],
            ranking_preferred_companies=["Company 1", "Company 2"],
            ranking_dealbreaker_keywords=["unpaid", "clearance"],
        ),
        now=NOW,
    )
    elapsed = time.perf_counter() - started
    print(f"\nre-scored 5,000 postings in {elapsed:.3f} s")
    assert elapsed < 3.0

    scores = dict(db.execute(select(Posting.source_key, Posting.local_score)).all())
    assert scores["bulk0"] == 40 + 5 + 15 + 10  # ML, Python, New York, today
    assert scores["bulk1"] == 15 + 10  # preferred company, posted an hour ago
    assert scores["bulk7"] == 10  # posted 7 hours ago, nothing else
