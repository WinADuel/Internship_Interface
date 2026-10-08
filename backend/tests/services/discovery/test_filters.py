"""Query-time filters, Inbox listing and match count (Phase 2 spec §4 and §7,
plan Task 6). Everything runs against the test database; no network."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from sqlalchemy import select

from app.models.app_settings import AppSettings
from app.models.posting import Posting, PostingSource, PostingState
from app.services.discovery.filters import (
    DISMISSED_CAP,
    DiscoveryFilters,
    filters_from_settings,
    inbox_clause,
    keyword_regex,
    list_postings,
    match_count,
)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
ANY = DiscoveryFilters()  # every list empty, sponsorship shown: matches everything

_seq = count()


def make(db, **overrides) -> Posting:
    n = next(_seq)
    values = {
        "source": PostingSource.SIMPLIFY,
        "source_key": f"k{n}",
        "company": "Acme",
        "title": "Software Engineer Intern",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/{n}",
        "url_key": f"https://jobs.example.com/{n}",
        "terms": ["Summer 2027"],
        "category": "Software",
        "sponsorship": "Other",
        "first_seen_at": NOW - timedelta(days=1),
        "last_seen_at": NOW,
        "state_changed_at": NOW - timedelta(days=1),
        "state": PostingState.NEW,
        "closed": False,
    }
    values.update(overrides)
    posting = Posting(**values)
    db.add(posting)
    db.flush()
    return posting


def inbox_ids(db, filters: DiscoveryFilters) -> set[int]:
    return set(db.scalars(select(Posting.id).where(inbox_clause(filters))))


def matches(db, filters: DiscoveryFilters, **posting) -> bool:
    p = make(db, **posting)
    return p.id in inbox_ids(db, filters)


# --- always-on rules ---------------------------------------------------------------


def test_empty_filters_match_every_new_open_posting_from_lists_and_boards(db_session):
    a = make(db_session, source=PostingSource.SIMPLIFY)
    b = make(db_session, source=PostingSource.VANSHB03, terms=["Summer"], category=None)
    c = make(db_session, source=PostingSource.LIST, terms=[], category=None)
    d = make(db_session, source=PostingSource.GREENHOUSE, terms=[], category=None, sponsorship=None)
    e = make(db_session, source=PostingSource.WORKDAY, terms=[], locations=[])
    assert inbox_ids(db_session, ANY) == {a.id, b.id, c.id, d.id, e.id}


def test_pasted_postings_never_reach_the_inbox(db_session):
    assert not matches(db_session, ANY, source=PostingSource.PASTED)


def test_closed_postings_never_reach_the_inbox(db_session):
    assert not matches(db_session, ANY, closed=True)


@pytest.mark.parametrize("state", [PostingState.SAVED, PostingState.DISMISSED, PostingState.APPLIED])
def test_only_new_postings_reach_the_inbox(db_session, state):
    assert not matches(db_session, ANY, state=state)


# --- term (lists only) ---------------------------------------------------------------


def test_term_must_match_for_list_postings(db_session):
    f = DiscoveryFilters(terms=("Summer 2027",))
    assert matches(db_session, f, terms=["Summer 2027"])
    assert matches(db_session, f, terms=["Fall 2026", "Summer 2027"])
    assert not matches(db_session, f, terms=["Fall 2026"])
    assert not matches(db_session, f, terms=[])


def test_term_match_ignores_case(db_session):
    assert matches(db_session, DiscoveryFilters(terms=("summer 2027",)), terms=["SUMMER 2027"])


def test_yearless_posting_term_matches_the_same_season_word(db_session):
    # vanshb03 rows carry a bare season word (progress log, Task 3 ruling).
    f = DiscoveryFilters(terms=("Summer 2027",))
    assert matches(db_session, f, source=PostingSource.VANSHB03, terms=["Summer"])
    assert matches(db_session, f, source=PostingSource.VANSHB03, terms=["summer"])
    assert matches(db_session, f, source=PostingSource.VANSHB03, terms=["Spring", "Summer"])
    assert not matches(db_session, f, source=PostingSource.VANSHB03, terms=["Fall"])
    fall = DiscoveryFilters(terms=("Fall 2026",))
    assert matches(db_session, fall, source=PostingSource.VANSHB03, terms=["Fall"])


def test_posting_term_with_another_year_does_not_match(db_session):
    f = DiscoveryFilters(terms=("Summer 2027",))
    assert not matches(db_session, f, terms=["Summer 2026"])


def test_term_rule_is_skipped_for_board_postings(db_session):
    f = DiscoveryFilters(terms=("Summer 2027",))
    assert matches(db_session, f, source=PostingSource.GREENHOUSE, terms=[])
    assert matches(db_session, f, source=PostingSource.LEVER, terms=["Fall 2025"])


# --- category (lists only) -----------------------------------------------------------


def test_category_must_be_one_of_the_chosen_ones(db_session):
    f = DiscoveryFilters(categories=("Software", "AI/ML/Data"))
    assert matches(db_session, f, category="Software")
    assert matches(db_session, f, category="ai/ml/data")
    assert not matches(db_session, f, category="Hardware")


def test_list_posting_without_a_category_passes_the_category_rule(db_session):
    # vanshb03 carries no category at all; hiding every one of its rows by
    # default would defeat the list (Task 6 ruling).
    f = DiscoveryFilters(categories=("Software",))
    assert matches(db_session, f, source=PostingSource.VANSHB03, category=None)


def test_category_rule_is_skipped_for_board_postings(db_session):
    f = DiscoveryFilters(categories=("Software",))
    assert matches(db_session, f, source=PostingSource.ASHBY, category="Hardware")


# --- include and watchlist keywords --------------------------------------------------


def test_include_keywords_need_a_whole_word_in_the_title(db_session):
    f = DiscoveryFilters(include_keywords=("software", "backend"))
    assert matches(db_session, f, title="SOFTWARE Engineering Intern")
    assert matches(db_session, f, title="Intern, Backend")
    assert not matches(db_session, f, title="Softwareless Intern")
    assert not matches(db_session, f, title="Hardware Intern")


def test_include_keywords_apply_to_board_postings_too(db_session):
    f = DiscoveryFilters(include_keywords=("software",))
    assert not matches(db_session, f, source=PostingSource.GREENHOUSE, terms=[], title="Data Intern")


def test_watchlist_keywords_apply_to_board_postings_only(db_session):
    f = DiscoveryFilters(watchlist_keywords=("intern", "internship", "co-op"))
    assert matches(db_session, f, source=PostingSource.GREENHOUSE, title="Software Engineering Intern")
    assert matches(db_session, f, source=PostingSource.WORKDAY, title="Co-op, Platform")
    assert not matches(db_session, f, source=PostingSource.LEVER, title="Software Engineer")
    # "International" is not the whole word "intern".
    assert not matches(db_session, f, source=PostingSource.ASHBY, title="International Payments Engineer")
    # List postings are internships by construction.
    assert matches(db_session, f, source=PostingSource.SIMPLIFY, title="Software Engineer")


def test_board_posting_needs_both_include_and_watchlist_keywords(db_session):
    f = DiscoveryFilters(include_keywords=("software",), watchlist_keywords=("intern",))
    board = {"source": PostingSource.GREENHOUSE, "terms": []}
    assert matches(db_session, f, title="Software Intern", **board)
    assert not matches(db_session, f, title="Software Engineer", **board)
    assert not matches(db_session, f, title="Data Intern", **board)


# --- exclude keywords ----------------------------------------------------------------


def test_exclude_keywords_hide_whole_word_matches_from_every_source(db_session):
    f = DiscoveryFilters(exclude_keywords=("senior", "phd"))
    assert not matches(db_session, f, title="Senior Software Intern")
    assert not matches(db_session, f, title="Research Intern (PhD)")
    assert not matches(db_session, f, source=PostingSource.GREENHOUSE, terms=[], title="SENIOR Engineer")
    assert matches(db_session, f, title="Seniority Systems Intern")
    assert matches(db_session, f, title="Software Intern")


# --- keyword escaping ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "title", "expected"),
    [
        ("c++", "C++ Developer Intern", True),
        ("c++", "Intern (C++/Rust)", True),
        ("c++", "Embedded c++", True),
        ("c++", "C Developer Intern", False),
        ("c++", "C++x Intern", False),
        ("co-op", "Software Co-op", True),
        ("co-op", "Software Coop", False),
        ("co-op", "Co-operative Intern", False),
        (".net", ".NET Developer Intern", True),
        (".net", "Intern - .net / C#", True),
        (".net", "Internet Intern", False),
        (".net", "Dotnet Intern", False),
        ("c#", "C# Intern", True),
        ("c#", "Intern, C#", True),
        ("c#", "C Intern", False),
        ("a.b", "axb Intern", False),
        ("a.b", "a.b Intern", True),
        ("(", "Intern ( Remote", True),
        ("(", "Intern (Remote)", False),
        ("[x", "Intern [x", True),
        ("50%", "50% remote Intern", True),
        ("back\\end", "back\\end intern", True),
        ("^", "Intern", False),
        ("machine learning", "Machine Learning Intern", True),
    ],
)
def test_keywords_with_regex_metacharacters_match_literally(db_session, keyword, title, expected):
    f = DiscoveryFilters(include_keywords=(keyword,))
    assert matches(db_session, f, title=title) is expected


def test_keyword_regex_ignores_blank_keywords():
    assert keyword_regex(()) is None
    assert keyword_regex(("  ", "")) is None
    assert keyword_regex(("intern",)) == r"(\mintern\M)"


# --- location -------------------------------------------------------------------------


def test_location_is_a_case_insensitive_substring_of_any_posting_location(db_session):
    f = DiscoveryFilters(locations=("new york", "Remote"))
    assert matches(db_session, f, locations=["Austin, TX", "New York, NY"])
    assert matches(db_session, f, locations=["Remote in USA"])
    assert not matches(db_session, f, locations=["Seattle, WA"])
    assert not matches(db_session, f, locations=[])


def test_location_applies_to_board_postings_too(db_session):
    f = DiscoveryFilters(locations=("Boston",))
    assert not matches(db_session, f, source=PostingSource.GREENHOUSE, terms=[], locations=["Denver"])


@pytest.mark.parametrize("pattern", ["%", "_", "\\", "N_w"])
def test_location_wildcards_are_literal(db_session, pattern):
    f = DiscoveryFilters(locations=(pattern,))
    assert not matches(db_session, f, locations=["New York, NY"])


def test_location_with_literal_wildcard_characters_still_matches(db_session):
    assert matches(db_session, DiscoveryFilters(locations=("100%",)), locations=["100% Remote"])
    assert matches(db_session, DiscoveryFilters(locations=("a_b",)), locations=["Site a_b"])
    assert matches(db_session, DiscoveryFilters(locations=("a\\b",)), locations=["x a\\b"])


# --- sponsorship ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["Does Not Offer Sponsorship", "U.S. Citizenship is Required"])
def test_hide_no_sponsorship_hides_marked_list_postings(db_session, value):
    assert not matches(db_session, DiscoveryFilters(hide_no_sponsorship=True), sponsorship=value)
    assert matches(db_session, DiscoveryFilters(hide_no_sponsorship=False), sponsorship=value)


@pytest.mark.parametrize("value", ["Other", "Offers Sponsorship", None])
def test_hide_no_sponsorship_keeps_other_list_postings(db_session, value):
    assert matches(db_session, DiscoveryFilters(hide_no_sponsorship=True), sponsorship=value)


def test_hide_no_sponsorship_is_skipped_for_board_postings(db_session):
    f = DiscoveryFilters(hide_no_sponsorship=True)
    assert matches(
        db_session, f, source=PostingSource.GREENHOUSE, terms=[], sponsorship="Does Not Offer Sponsorship"
    )


# --- settings -------------------------------------------------------------------------


def test_filters_from_settings_reads_the_discovery_fields():
    s = AppSettings(
        id=1,
        discovery_terms=["Summer 2027"],
        discovery_categories=["Software"],
        discovery_include_keywords=["software"],
        discovery_watchlist_keywords=["intern"],
        discovery_exclude_keywords=["senior"],
        discovery_locations=["Remote"],
        discovery_hide_no_sponsorship=True,
    )
    assert filters_from_settings(s) == DiscoveryFilters(
        terms=("Summer 2027",),
        categories=("Software",),
        include_keywords=("software",),
        watchlist_keywords=("intern",),
        exclude_keywords=("senior",),
        locations=("Remote",),
        hide_no_sponsorship=True,
    )


def test_filters_accept_lists_and_are_hashable():
    f = DiscoveryFilters(terms=["Summer 2027"], locations=["Remote"])
    assert f.terms == ("Summer 2027",)
    assert hash(f) == hash(DiscoveryFilters(terms=("Summer 2027",), locations=("Remote",)))


def test_default_settings_filters_hide_hardware_old_terms_and_senior_roles(db_session):
    f = filters_from_settings(AppSettings(id=1, **_defaults()))
    keep = make(db_session, title="Software Engineer Intern")
    vansh = make(db_session, source=PostingSource.VANSHB03, terms=["Summer"], category=None)
    board = make(db_session, source=PostingSource.GREENHOUSE, terms=[], category=None, title="SWE Intern")
    make(db_session, category="Hardware")
    make(db_session, terms=["Summer 2026"])
    make(db_session, title="Senior Software Intern")
    make(db_session, source=PostingSource.GREENHOUSE, terms=[], category=None, title="Software Engineer")
    assert inbox_ids(db_session, f) == {keep.id, vansh.id, board.id}


def _defaults() -> dict:
    from app.models import app_settings as m

    return {
        "discovery_terms": list(m.DEFAULT_TERMS),
        "discovery_categories": list(m.DEFAULT_CATEGORIES),
        "discovery_include_keywords": [],
        "discovery_watchlist_keywords": list(m.DEFAULT_WATCHLIST_KEYWORDS),
        "discovery_exclude_keywords": list(m.DEFAULT_EXCLUDE_KEYWORDS),
        "discovery_locations": [],
        "discovery_hide_no_sponsorship": False,
    }


# --- list_postings ---------------------------------------------------------------------


def test_inbox_orders_by_score_then_posted_date_then_id(db_session):
    old = make(db_session, date_posted=NOW - timedelta(days=5))
    recent = make(db_session, date_posted=NOW - timedelta(days=1))
    # No date_posted: first_seen_at stands in.
    seen_recently = make(db_session, date_posted=None, first_seen_at=NOW - timedelta(days=2))
    tie_a = make(db_session, date_posted=NOW - timedelta(days=3))
    tie_b = make(db_session, date_posted=NOW - timedelta(days=3))
    scored_low = make(db_session, claude_score=10, date_posted=NOW - timedelta(days=30))
    scored_high = make(db_session, claude_score=90, date_posted=NOW - timedelta(days=30))

    items, total = list_postings(db_session, "inbox", ANY)
    assert [p.id for p in items] == [
        scored_high.id,
        scored_low.id,
        recent.id,
        seen_recently.id,
        tie_b.id,
        tie_a.id,
        old.id,
    ]
    assert total == 7


def test_inbox_applies_filters_and_excludes_other_states(db_session):
    shown = make(db_session, title="Software Intern")
    make(db_session, title="Senior Software Intern")
    make(db_session, state=PostingState.SAVED)
    make(db_session, closed=True)
    make(db_session, source=PostingSource.PASTED)
    items, total = list_postings(db_session, "inbox", DiscoveryFilters(exclude_keywords=("senior",)))
    assert [p.id for p in items] == [shown.id]
    assert total == 1


def test_inbox_pagination_reports_the_full_total(db_session):
    made = [make(db_session, date_posted=NOW - timedelta(days=i)) for i in range(7)]
    page1, total1 = list_postings(db_session, "inbox", ANY, limit=3, offset=0)
    page3, total3 = list_postings(db_session, "inbox", ANY, limit=3, offset=6)
    beyond, total4 = list_postings(db_session, "inbox", ANY, limit=3, offset=10)
    assert [p.id for p in page1] == [p.id for p in made[:3]]
    assert [p.id for p in page3] == [made[6].id]
    assert beyond == []
    assert total1 == total3 == total4 == 7


def test_saved_lists_saved_postings_newest_first_including_closed_and_ignores_filters(db_session):
    older = make(db_session, state=PostingState.SAVED, state_changed_at=NOW - timedelta(days=2))
    newer = make(
        db_session,
        state=PostingState.SAVED,
        state_changed_at=NOW - timedelta(hours=1),
        closed=True,
        source=PostingSource.PASTED,
        title="Senior Engineer",
    )
    make(db_session, state=PostingState.NEW)
    make(db_session, state=PostingState.APPLIED)
    items, total = list_postings(db_session, "saved", DiscoveryFilters(exclude_keywords=("senior",)))
    assert [p.id for p in items] == [newer.id, older.id]
    assert total == 2


def test_dismissed_lists_newest_first(db_session):
    older = make(db_session, state=PostingState.DISMISSED, state_changed_at=NOW - timedelta(days=2))
    newer = make(db_session, state=PostingState.DISMISSED, state_changed_at=NOW - timedelta(days=1))
    make(db_session, state=PostingState.SAVED)
    items, total = list_postings(db_session, "dismissed", ANY)
    assert [p.id for p in items] == [newer.id, older.id]
    assert total == 2


def test_dismissed_is_capped_at_the_most_recent_200(db_session):
    assert DISMISSED_CAP == 200
    made = [
        make(db_session, state=PostingState.DISMISSED, state_changed_at=NOW - timedelta(minutes=i))
        for i in range(DISMISSED_CAP + 5)
    ]
    first, total = list_postings(db_session, "dismissed", ANY, limit=100, offset=0)
    tail, total_tail = list_postings(db_session, "dismissed", ANY, limit=100, offset=150)
    beyond, total_beyond = list_postings(db_session, "dismissed", ANY, limit=100, offset=200)
    assert total == total_tail == total_beyond == DISMISSED_CAP
    assert [p.id for p in first] == [p.id for p in made[:100]]
    assert [p.id for p in tail] == [p.id for p in made[150:200]]
    assert beyond == []


def test_list_postings_rejects_unknown_views_and_bad_paging(db_session):
    with pytest.raises(ValueError):
        list_postings(db_session, "applied", ANY)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        list_postings(db_session, "inbox", ANY, limit=0)
    with pytest.raises(ValueError):
        list_postings(db_session, "inbox", ANY, offset=-1)


# --- match_count -----------------------------------------------------------------------


def test_match_count_counts_the_inbox_for_unsaved_filters(db_session):
    make(db_session, title="Software Intern", locations=["Boston, MA"])
    make(db_session, title="Data Intern", locations=["Remote"])
    make(db_session, title="Software Intern", locations=["Remote"], closed=True)
    make(db_session, title="Software Intern", state=PostingState.SAVED)
    assert match_count(db_session, ANY) == 2
    assert match_count(db_session, DiscoveryFilters(include_keywords=("software",))) == 1
    assert match_count(db_session, DiscoveryFilters(locations=("remote",))) == 1
    assert match_count(db_session, DiscoveryFilters(locations=("Tokyo",))) == 0
    _, total = list_postings(db_session, "inbox", DiscoveryFilters(include_keywords=("software",)))
    assert total == 1
