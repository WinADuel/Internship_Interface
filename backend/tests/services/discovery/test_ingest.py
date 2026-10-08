"""Ingest and housekeeping (Phase 2 spec §3, plan Task 5).

Everything runs against the test database through `db_session`; no network.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.posting import Posting, PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.services.discovery.ingest import IngestStats, housekeep, ingest
from app.services.discovery.parsers import PostingIn
from app.services.discovery.sources import SourceResult

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)


def pin(
    key: str,
    *,
    source: PostingSource = PostingSource.SIMPLIFY,
    company: str = "Acme",
    title: str | None = None,
    url: str | None = None,
    active: bool = True,
    locations: list[str] | None = None,
    terms: list[str] | None = None,
    category: str | None = "Software",
    sponsorship: str | None = "Other",
) -> PostingIn:
    return PostingIn(
        source=source,
        source_key=key,
        company=company,
        title=title if title is not None else f"Software Intern {key}",
        locations=locations if locations is not None else ["Remote"],
        url=url
        if url is not None
        else f"https://jobs.example.com/{source.value}/{key}",
        terms=terms if terms is not None else ["Summer 2027"],
        category=category,
        sponsorship=sponsorship,
        date_posted=None,
        active=active,
    )


def result(
    postings: list[PostingIn],
    *,
    source: PostingSource | None = PostingSource.SIMPLIFY,
    complete: bool = True,
    error: str | None = None,
    key_prefix: str | None = None,
    name: str = "Simplify list",
) -> SourceResult:
    return SourceResult(
        name,
        postings,
        complete=complete,
        error=error,
        key_prefix=key_prefix,
        source=source,
    )


def all_postings(db) -> list[Posting]:
    return list(db.scalars(select(Posting).order_by(Posting.id)))


def by_key(db, source: PostingSource, key: str) -> Posting:
    return db.scalars(
        select(Posting).where(Posting.source == source, Posting.source_key == key)
    ).one()


def watch(db, token: str = "acme", ats: WatchAts = WatchAts.GREENHOUSE) -> WatchCompany:
    company = WatchCompany(
        name=token.title(),
        ats=ats,
        board_token=token,
        careers_url=f"https://x.test/{token}",
    )
    db.add(company)
    db.flush()
    return company


def stored(db, key: str, **overrides) -> Posting:
    """A posting already in the table, written directly (not via ingest)."""
    values = {
        "source": PostingSource.SIMPLIFY,
        "source_key": key,
        "company": "Acme",
        "title": f"Software Intern {key}",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/stored/{key}",
        "url_key": f"https://jobs.example.com/stored/{key}",
        "terms": ["Summer 2027"],
        "first_seen_at": NOW - timedelta(days=1),
        "last_seen_at": NOW - timedelta(days=1),
        "state_changed_at": NOW - timedelta(days=1),
        "state": PostingState.NEW,
        "closed": False,
    }
    values.update(overrides)
    posting = Posting(**values)
    db.add(posting)
    db.flush()
    return posting


# --- inserts and updates ----------------------------------------------------------


def test_new_active_postings_are_inserted_as_new(db_session):
    stats = ingest(db_session, result([pin("a"), pin("b")]), NOW)

    assert stats == IngestStats(added=2, updated=0, closed=0, skipped_duplicates=0)
    rows = all_postings(db_session)
    assert [r.source_key for r in rows] == ["a", "b"]
    row = rows[0]
    assert row.source is PostingSource.SIMPLIFY
    assert row.state is PostingState.NEW
    assert row.closed is False
    assert row.first_seen_at == NOW
    assert row.last_seen_at == NOW
    assert row.state_changed_at == NOW
    assert row.url_key == "https://jobs.example.com/simplify/a"
    assert row.locations == ["Remote"]
    assert row.terms == ["Summer 2027"]
    assert row.category == "Software"
    assert row.sponsorship == "Other"
    assert row.watch_company_id is None


def test_url_key_is_normalized(db_session):
    ingest(
        db_session,
        result([pin("a", url="HTTPS://Jobs.Example.com/x/?utm_source=simplify#apply")]),
        NOW,
    )
    assert all_postings(db_session)[0].url_key == "https://jobs.example.com/x"


def test_row_with_unusable_url_is_skipped(db_session):
    stats = ingest(
        db_session, result([pin("a", url="javascript:alert(1)"), pin("b")]), NOW
    )
    assert stats.added == 1
    assert [r.source_key for r in all_postings(db_session)] == ["b"]


def test_new_inactive_posting_is_ignored(db_session):
    stats = ingest(db_session, result([pin("a", active=False)]), NOW)
    assert stats == IngestStats(added=0, updated=0, closed=0, skipped_duplicates=0)
    assert all_postings(db_session) == []


def test_reingesting_the_same_result_adds_nothing(db_session):
    postings = [pin("a"), pin("b"), pin("c")]
    ingest(db_session, result(postings), NOW)

    stats = ingest(db_session, result(postings), LATER)

    assert stats == IngestStats(added=0, updated=3, closed=0, skipped_duplicates=0)
    rows = all_postings(db_session)
    assert len(rows) == 3
    assert all(r.first_seen_at == NOW and r.last_seen_at == LATER for r in rows)


def test_existing_posting_is_updated_but_keeps_state_and_claude_fields(db_session):
    existing = stored(
        db_session,
        "a",
        state=PostingState.SAVED,
        claude_score=80,
        claude_note="good fit",
        state_changed_at=NOW - timedelta(days=3),
    )
    changed = pin(
        "a",
        company="Acme Corp",
        title="ML Intern",
        url="https://jobs.example.com/new-url?utm_medium=x",
        locations=["NYC", "SF"],
        terms=["Fall 2027"],
        category="AI/ML/Data",
        sponsorship="Offers Sponsorship",
    )

    stats = ingest(db_session, result([changed]), NOW)

    assert stats == IngestStats(added=0, updated=1, closed=0, skipped_duplicates=0)
    db_session.refresh(existing)
    assert existing.company == "Acme Corp"
    assert existing.title == "ML Intern"
    assert existing.url == "https://jobs.example.com/new-url?utm_medium=x"
    assert existing.url_key == "https://jobs.example.com/new-url"
    assert existing.locations == ["NYC", "SF"]
    assert existing.terms == ["Fall 2027"]
    assert existing.category == "AI/ML/Data"
    assert existing.sponsorship == "Offers Sponsorship"
    assert existing.last_seen_at == NOW
    assert existing.first_seen_at == NOW - timedelta(days=1)
    assert existing.state is PostingState.SAVED
    assert existing.state_changed_at == NOW - timedelta(days=3)
    assert existing.claude_score == 80
    assert existing.claude_note == "good fit"


def test_existing_posting_marked_inactive_is_closed_and_reopens_when_active(db_session):
    existing = stored(db_session, "a")

    stats = ingest(db_session, result([pin("a", active=False)], complete=False), NOW)
    assert stats.closed == 1
    db_session.refresh(existing)
    assert existing.closed is True

    stats = ingest(db_session, result([pin("a")], complete=False), LATER)
    db_session.refresh(existing)
    assert existing.closed is False
    assert stats.closed == 0


def test_applied_posting_keeps_application_link_on_update(db_session):
    existing = stored(db_session, "a", state=PostingState.APPLIED)
    ingest(db_session, result([pin("a", title="Renamed")]), NOW)
    db_session.refresh(existing)
    assert existing.state is PostingState.APPLIED
    assert existing.title == "Renamed"


# --- de-duplication ---------------------------------------------------------------


def test_same_role_from_simplify_vanshb03_and_greenhouse_is_one_posting(db_session):
    company = watch(db_session)
    url = "https://boards.greenhouse.io/acme/jobs/123"
    simplify = pin(
        "s-1",
        url=f"{url}?utm_source=Simplify&ref=simplify",
        title="Software Engineer Intern",
    )
    vansh = pin(
        "v-1",
        source=PostingSource.VANSHB03,
        company="ACME",
        title="software engineer intern",
        url="https://acme.example.com/careers/123",  # different link, same role
    )
    board = pin(
        "123",
        source=PostingSource.GREENHOUSE,
        url=url,
        title="Software Engineer Intern",
        terms=[],
        category=None,
        sponsorship=None,
    )

    s1 = ingest(db_session, result([simplify]), NOW)
    s2 = ingest(
        db_session,
        result([vansh], source=PostingSource.VANSHB03, name="vanshb03 list"),
        NOW,
    )
    s3 = ingest(
        db_session,
        result([board], source=PostingSource.GREENHOUSE, name="Acme"),
        NOW,
        watch_company_id=company.id,
    )

    assert (s1.added, s2.added, s3.added) == (1, 0, 0)
    assert (s2.skipped_duplicates, s3.skipped_duplicates) == (1, 1)
    rows = all_postings(db_session)
    assert len(rows) == 1
    assert rows[0].source is PostingSource.SIMPLIFY


def test_url_key_duplicate_of_any_existing_posting_is_skipped(db_session):
    # Even an old posting, from any source, in any state.
    stored(
        db_session,
        "old",
        source=PostingSource.PASTED,
        url_key="https://jobs.example.com/role",
        first_seen_at=NOW - timedelta(days=60),
        state=PostingState.DISMISSED,
    )
    stats = ingest(
        db_session, result([pin("a", url="https://jobs.example.com/role/")]), NOW
    )
    assert stats == IngestStats(added=0, updated=0, closed=0, skipped_duplicates=1)


def test_company_title_duplicate_only_within_14_days(db_session):
    stored(
        db_session,
        "recent",
        source=PostingSource.VANSHB03,
        company="Acme",
        title="Data Intern",
        first_seen_at=NOW - timedelta(days=13),
    )
    stored(
        db_session,
        "old",
        source=PostingSource.VANSHB03,
        company="Beta",
        title="Data Intern",
        first_seen_at=NOW - timedelta(days=15),
    )
    stats = ingest(
        db_session,
        result(
            [
                pin("a", company="acme", title="DATA INTERN"),
                pin("b", company="Beta", title="Data Intern"),
            ]
        ),
        NOW,
    )
    assert stats.added == 1
    assert stats.skipped_duplicates == 1
    assert by_key(db_session, PostingSource.SIMPLIFY, "b").company == "Beta"


def test_company_title_match_from_the_same_source_is_not_a_duplicate(db_session):
    # A list often has the same title twice (two terms, two offices) with
    # different links; only another source's copy counts as a duplicate.
    stored(db_session, "x", company="Acme", title="Data Intern")
    stats = ingest(
        db_session,
        result(
            [
                pin("x", company="Acme", title="Data Intern"),
                pin("y", company="Acme", title="Data Intern", terms=["Fall 2027"]),
                pin("z", company="Acme", title="Data Intern", terms=["Spring 2027"]),
            ]
        ),
        NOW,
    )
    assert stats == IngestStats(added=2, updated=1, closed=0, skipped_duplicates=0)


def test_duplicates_within_one_result_are_inserted_once(db_session):
    stats = ingest(
        db_session,
        result(
            [
                pin("a", url="https://jobs.example.com/same"),
                pin("b", url="https://jobs.example.com/same?utm_campaign=x"),
                pin("a", title="Repeated key"),
            ]
        ),
        NOW,
    )
    assert stats == IngestStats(added=1, updated=0, closed=0, skipped_duplicates=2)
    rows = all_postings(db_session)
    assert [(r.source_key, r.title) for r in rows] == [("a", "Software Intern a")]


def test_existing_posting_is_updated_even_if_its_url_now_matches_another(db_session):
    # De-duplication applies to new postings only; an existing (source, key)
    # is always updated.
    stored(
        db_session,
        "other",
        source=PostingSource.VANSHB03,
        url_key="https://jobs.example.com/z",
    )
    existing = stored(db_session, "a")
    stats = ingest(
        db_session, result([pin("a", url="https://jobs.example.com/z")]), NOW
    )
    assert stats.updated == 1
    db_session.refresh(existing)
    assert existing.url_key == "https://jobs.example.com/z"


# --- closing ----------------------------------------------------------------------


def test_complete_result_closes_postings_it_no_longer_lists(db_session):
    ingest(db_session, result([pin("a"), pin("b"), pin("c")]), NOW)
    saved = by_key(db_session, PostingSource.SIMPLIFY, "b")
    saved.state = PostingState.SAVED
    db_session.flush()

    stats = ingest(db_session, result([pin("a")]), LATER)

    assert stats == IngestStats(added=0, updated=1, closed=2, skipped_duplicates=0)
    assert by_key(db_session, PostingSource.SIMPLIFY, "a").closed is False
    c = by_key(db_session, PostingSource.SIMPLIFY, "c")
    assert c.closed is True
    assert c.last_seen_at == NOW
    b = by_key(db_session, PostingSource.SIMPLIFY, "b")
    assert b.closed is True
    assert b.state is PostingState.SAVED


def test_already_closed_postings_are_not_counted_again(db_session):
    stored(db_session, "gone", closed=True)
    stats = ingest(db_session, result([pin("a")]), NOW)
    assert stats.closed == 0


def test_empty_complete_result_closes_everything_from_that_source(db_session):
    stored(db_session, "a")
    stored(db_session, "v", source=PostingSource.VANSHB03)
    stats = ingest(db_session, result([]), NOW)
    assert stats.closed == 1
    assert by_key(db_session, PostingSource.SIMPLIFY, "a").closed is True
    assert by_key(db_session, PostingSource.VANSHB03, "v").closed is False


def test_incomplete_result_closes_nothing(db_session):
    stored(db_session, "a")
    stats = ingest(db_session, result([pin("b")], complete=False), NOW)
    assert stats.closed == 0
    assert by_key(db_session, PostingSource.SIMPLIFY, "a").closed is False


def test_not_modified_result_changes_nothing(db_session):
    existing = stored(db_session, "a")
    nm = SourceResult(
        "Simplify list", [], complete=False, not_modified=True, etag='"x"'
    )
    assert ingest(db_session, nm, NOW) == IngestStats(0, 0, 0, 0)
    db_session.refresh(existing)
    assert existing.closed is False
    assert existing.last_seen_at == NOW - timedelta(days=1)


def test_closing_does_not_touch_other_sources(db_session):
    stored(db_session, "v", source=PostingSource.VANSHB03)
    ingest(db_session, result([pin("a")]), NOW)
    assert by_key(db_session, PostingSource.VANSHB03, "v").closed is False


def test_custom_list_closes_only_its_own_prefixed_keys(db_session):
    stored(db_session, "aaaa:1", source=PostingSource.LIST)
    stored(db_session, "aaaa:2", source=PostingSource.LIST)
    stored(db_session, "bbbb:1", source=PostingSource.LIST)
    stored(db_session, "aaaa1", source=PostingSource.LIST)  # no colon: not this list's
    stats = ingest(
        db_session,
        result(
            [pin("aaaa:1", source=PostingSource.LIST)],
            source=PostingSource.LIST,
            key_prefix="aaaa",
            name="Custom list",
        ),
        NOW,
    )
    assert stats.closed == 1
    assert by_key(db_session, PostingSource.LIST, "aaaa:2").closed is True
    assert by_key(db_session, PostingSource.LIST, "aaaa:1").closed is False
    assert by_key(db_session, PostingSource.LIST, "bbbb:1").closed is False
    assert by_key(db_session, PostingSource.LIST, "aaaa1").closed is False


def test_custom_list_prefix_is_matched_literally(db_session):
    stored(db_session, "a_x:1", source=PostingSource.LIST)
    stored(db_session, "a%:1", source=PostingSource.LIST)
    ingest(db_session, result([], source=PostingSource.LIST, key_prefix="a%"), NOW)
    assert by_key(db_session, PostingSource.LIST, "a%:1").closed is True
    assert by_key(db_session, PostingSource.LIST, "a_x:1").closed is False


def test_board_result_sets_watch_company_and_closes_only_that_company(db_session):
    acme = watch(db_session, "acme")
    beta = watch(db_session, "beta")
    gh = PostingSource.GREENHOUSE
    ingest(
        db_session,
        result([pin("1", source=gh), pin("2", source=gh)], source=gh),
        NOW,
        watch_company_id=acme.id,
    )
    ingest(
        db_session,
        result([pin("9", source=gh)], source=gh),
        NOW,
        watch_company_id=beta.id,
    )
    assert by_key(db_session, gh, "1").watch_company_id == acme.id
    assert by_key(db_session, gh, "9").watch_company_id == beta.id

    stats = ingest(
        db_session,
        result([pin("1", source=gh)], source=gh),
        LATER,
        watch_company_id=acme.id,
    )

    assert stats.closed == 1
    assert by_key(db_session, gh, "2").closed is True
    assert by_key(db_session, gh, "9").closed is False


def test_board_result_without_watch_company_closes_nothing(db_session):
    stored(db_session, "1", source=PostingSource.GREENHOUSE)
    stats = ingest(db_session, result([], source=PostingSource.GREENHOUSE), NOW)
    assert stats.closed == 0
    assert by_key(db_session, PostingSource.GREENHOUSE, "1").closed is False


def test_workday_result_is_incomplete_and_closes_nothing(db_session):
    company = watch(
        db_session, "nvidia.wd5.myworkdayjobs.com/nvidia/site", WatchAts.WORKDAY
    )
    wd = PostingSource.WORKDAY
    stored(db_session, "old", source=wd, watch_company_id=company.id)
    stats = ingest(
        db_session,
        result([pin("new", source=wd)], source=wd, complete=False),
        NOW,
        watch_company_id=company.id,
    )
    assert stats.added == 1
    assert stats.closed == 0
    assert by_key(db_session, wd, "old").closed is False


def test_failed_source_changes_nothing(db_session):
    existing = stored(db_session, "a")
    failed = SourceResult(
        "Simplify list",
        [pin("a", title="Changed"), pin("b")],
        complete=True,
        error="Simplify list: status 500",
        source=PostingSource.SIMPLIFY,
    )
    assert ingest(db_session, failed, NOW) == IngestStats(0, 0, 0, 0)
    db_session.refresh(existing)
    assert existing.title == "Software Intern a"
    assert existing.closed is False
    assert [r.source_key for r in all_postings(db_session)] == ["a"]


def test_source_falls_back_to_the_postings_when_result_has_none(db_session):
    stored(db_session, "gone")
    stats = ingest(db_session, result([pin("a")], source=None), NOW)
    assert stats.added == 1
    assert stats.closed == 1


# --- volume -----------------------------------------------------------------------


def test_five_thousand_rows_ingest_in_one_call(db_session):
    # No timing assertion (CI timing is noisy); this checks the bulk path
    # completes and counts stay right at list scale.
    postings = [
        pin(f"k{i}", company=f"Company {i % 700}", title=f"Intern {i}")
        for i in range(5000)
    ]
    stats = ingest(db_session, result(postings), NOW)
    assert stats == IngestStats(added=5000, updated=0, closed=0, skipped_duplicates=0)

    again = ingest(db_session, result(postings[:4000]), LATER)
    assert again == IngestStats(
        added=0, updated=4000, closed=1000, skipped_duplicates=0
    )
    assert len(all_postings(db_session)) == 5000


# --- housekeeping -----------------------------------------------------------------


def test_housekeep_deletes_closed_or_unseen_new_and_dismissed_only(db_session):
    def days(n: int) -> datetime:
        return NOW - timedelta(days=n)

    keep = {
        "new-unseen-89": {"first_seen_at": days(120), "last_seen_at": days(89)},
        "dismissed-unseen-89": {
            "first_seen_at": days(120),
            "last_seen_at": days(89),
            "state": PostingState.DISMISSED,
        },
        "saved-closed": {"closed": True, "state": PostingState.SAVED},
        "saved-unseen-91": {
            "first_seen_at": days(120),
            "last_seen_at": days(91),
            "state": PostingState.SAVED,
        },
        "applied-closed-unseen-91": {
            "closed": True,
            "first_seen_at": days(120),
            "last_seen_at": days(91),
            "state": PostingState.APPLIED,
        },
    }
    drop = {
        "new-unseen-91": {"first_seen_at": days(120), "last_seen_at": days(91)},
        "dismissed-unseen-91": {
            "first_seen_at": days(120),
            "last_seen_at": days(91),
            "state": PostingState.DISMISSED,
        },
        "new-closed": {"closed": True},
        "dismissed-closed": {"closed": True, "state": PostingState.DISMISSED},
    }
    for key, overrides in {**keep, **drop}.items():
        stored(db_session, key, **overrides)

    assert housekeep(db_session, NOW) == len(drop)
    assert sorted(r.source_key for r in all_postings(db_session)) == sorted(keep)


def test_housekeep_keeps_old_postings_that_are_still_listed(db_session):
    # Deleting a still-listed dismissed posting would bring it back to the
    # Inbox as new on the next scan.
    old = NOW - timedelta(days=120)
    stored(db_session, "dismissed", first_seen_at=old, state=PostingState.DISMISSED)
    stored(db_session, "new", first_seen_at=old)
    ingest(db_session, result([pin("dismissed"), pin("new")]), NOW)

    assert housekeep(db_session, NOW) == 0
    dismissed = by_key(db_session, PostingSource.SIMPLIFY, "dismissed")
    assert dismissed.state is PostingState.DISMISSED
    assert dismissed.first_seen_at == old


def test_housekeep_with_nothing_to_delete_returns_zero(db_session):
    stored(db_session, "fresh")
    assert housekeep(db_session, NOW) == 0
