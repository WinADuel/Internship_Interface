"""Scanner: one full scan over every list and watched board, single-flight
under a Postgres advisory lock (Phase 2 spec §5, plan Task 7).

Every request goes through `FakeDiscoveryHttp`; no test touches the network.
Tests that need "another scanner" hold the lock on a separate connection
from the test engine, released in teardown.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, text

from app.models.app_settings import DEFAULT_LIST_URLS
from app.models.posting import Posting, PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.services import settings_service
from app.services.discovery import scanner, sources, watchlist
from app.services.discovery.http import DiscoveryFetchError, FetchResult
from app.services.discovery.scanner import (
    LAST_SCAN_ERROR_MAX,
    SCAN_LOCK_KEY,
    ScanReport,
    is_scan_running,
    run_scan,
    scan_status,
)
from tests.services.discovery.fakes import FakeCall, FakeDiscoveryHttp, json_result

NOW = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)

SIMPLIFY_URL, VANSHB03_URL = DEFAULT_LIST_URLS
GH_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{token}?mode=json"


# --- builders ----------------------------------------------------------------


def list_row(n: int, *, title: str = "Software Engineer Intern", active: bool = True) -> dict:
    return {
        "source": "Simplify",
        "category": "Software",
        "company_name": f"List Co {n}",
        "id": f"row-{n}",
        "title": title,
        "active": active,
        "terms": ["Summer 2027"],
        "date_posted": 1775081547,
        "url": f"https://jobs.example.com/list/{n}",
        "locations": ["Remote"],
        "is_visible": True,
        "sponsorship": "Other",
    }


def gh_job(n: int, token: str = "acme", title: str = "Software Engineering Intern") -> dict:
    return {
        "id": n,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/{token}/jobs/{n}",
        "location": {"name": "Remote"},
        "first_published": "2026-09-28T09:30:00-04:00",
    }


def lever_job(job_id: str, token: str = "beta", title: str = "Data Science Intern") -> dict:
    return {
        "id": job_id,
        "text": title,
        "hostedUrl": f"https://jobs.lever.co/{token}/{job_id}",
        "categories": {"location": "Remote"},
        "createdAt": 1775081547000,
    }


def not_modified(etag: str | None = None) -> FetchResult:
    return FetchResult(status=304, data=None, text=None, etag=etag, final_url="https://x.test/")


def add_company(db, name: str, ats: WatchAts, token: str, **kwargs) -> WatchCompany:
    company = WatchCompany(
        name=name, ats=ats, board_token=token, careers_url=f"https://x.test/{token}", **kwargs
    )
    db.add(company)
    db.commit()
    return company


def configure(db, *, list_urls=(SIMPLIFY_URL, VANSHB03_URL), etags=None, keywords=None):
    s = settings_service.get_settings(db)
    s.discovery_list_urls = list(list_urls)
    s.discovery_list_etags = dict(etags or {})
    if keywords is not None:
        s.discovery_watchlist_keywords = list(keywords)
    db.commit()
    return s


class Pauses:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def postings(db) -> list[Posting]:
    return list(db.scalars(select(Posting).order_by(Posting.id)))


def full_http(overrides: dict | None = None) -> FakeDiscoveryHttp:
    responses = {
        ("GET", SIMPLIFY_URL): json_result([list_row(1)], etag='"s1"'),
        ("GET", VANSHB03_URL): json_result([list_row(2) | {"source": "vanshb03"}], etag='"v1"'),
        ("GET", GH_API.format(token="acme")): json_result({"jobs": [gh_job(11), gh_job(12)]}),
        ("GET", LEVER_API.format(token="beta")): json_result([lever_job("aaa-1")]),
    }
    responses.update(overrides or {})
    return FakeDiscoveryHttp(responses)


@pytest.fixture()
def other_connection(_engine):
    """A second database session, standing in for another scanner."""
    conn = _engine.connect()
    yield conn
    conn.execute(text("SELECT pg_advisory_unlock_all()"))
    conn.rollback()
    conn.close()


def try_lock(conn) -> bool:
    return conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCAN_LOCK_KEY}).scalar_one()


def unlock(conn) -> bool:
    return conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCAN_LOCK_KEY}).scalar_one()


# --- a full scan -------------------------------------------------------------


def test_full_scan_ingests_lists_and_boards_and_records_etags(db_session):
    db = db_session
    configure(db)
    acme = add_company(db, "Acme", WatchAts.GREENHOUSE, "acme")
    beta = add_company(db, "Beta", WatchAts.LEVER, "beta")
    http = full_http()
    pauses = Pauses()

    report = run_scan(db, http, now=NOW, pause=pauses)

    assert report == ScanReport(added=5, closed=0, removed=0, errors=[])
    rows = postings(db)
    assert len(rows) == 5
    by_source = {}
    for row in rows:
        by_source.setdefault(row.source, []).append(row)
    assert {s: len(v) for s, v in by_source.items()} == {
        PostingSource.SIMPLIFY: 1,
        PostingSource.VANSHB03: 1,
        PostingSource.GREENHOUSE: 2,
        PostingSource.LEVER: 1,
    }
    assert all(r.watch_company_id == acme.id for r in by_source[PostingSource.GREENHOUSE])
    assert by_source[PostingSource.LEVER][0].watch_company_id == beta.id
    assert all(r.watch_company_id is None for r in by_source[PostingSource.SIMPLIFY])
    assert all(r.first_seen_at == NOW and r.state is PostingState.NEW for r in rows)

    # Lists first (no stored ETag yet), then boards in id order.
    assert [(c.method, c.url, c.etag) for c in http.calls] == [
        ("GET", SIMPLIFY_URL, None),
        ("GET", VANSHB03_URL, None),
        ("GET", GH_API.format(token="acme"), None),
        ("GET", LEVER_API.format(token="beta"), None),
    ]
    # A short pause between companies, not before the first or after the last.
    assert pauses.calls == [1.0]

    s = settings_service.get_settings(db)
    assert s.discovery_list_etags == {SIMPLIFY_URL: '"s1"', VANSHB03_URL: '"v1"'}
    assert s.last_scan_at == NOW
    assert s.last_scan_error is None
    for company in (acme, beta):
        db.refresh(company)
        assert company.last_checked_at == NOW
        assert company.last_error is None


def test_second_scan_sends_stored_etags_and_304_refreshes_last_seen(db_session):
    db = db_session
    configure(db)
    run_scan(db, full_http(), now=NOW, pause=Pauses())

    later = NOW + timedelta(hours=6)
    http = full_http(
        {
            ("GET", SIMPLIFY_URL): not_modified(),
            # A 304 may carry a fresh ETag; it is stored.
            ("GET", VANSHB03_URL): not_modified('"v2"'),
        }
    )
    report = run_scan(db, http, now=later, pause=Pauses())

    assert report == ScanReport(added=0, closed=0, removed=0, errors=[])
    assert [(c.url, c.etag) for c in http.calls] == [(SIMPLIFY_URL, '"s1"'), (VANSHB03_URL, '"v1"')]
    # Nothing ingested, but an unchanged list still lists its postings, so
    # they count as seen now (else housekeeping would eventually delete them).
    after = postings(db)
    assert [p.last_seen_at for p in after] == [later, later]
    assert [p.first_seen_at for p in after] == [NOW, NOW]
    assert not any(p.closed for p in after)
    s = settings_service.get_settings(db)
    assert s.discovery_list_etags == {SIMPLIFY_URL: '"s1"', VANSHB03_URL: '"v2"'}
    assert s.last_scan_at == later


def test_304_lists_postings_are_never_housekept_while_the_list_is_unchanged(db_session):
    db = db_session
    configure(db, list_urls=[SIMPLIFY_URL])
    run_scan(
        db,
        FakeDiscoveryHttp(
            {("GET", SIMPLIFY_URL): json_result([list_row(1), list_row(2)], etag='"a"')}
        ),
        now=NOW,
        pause=Pauses(),
    )
    # A dismissed posting the list still carries, and a closed one.
    rows = postings(db)
    rows[0].state = PostingState.DISMISSED
    rows[1].closed = True
    db.commit()

    much_later = NOW + timedelta(days=200)
    report = run_scan(
        db,
        FakeDiscoveryHttp({("GET", SIMPLIFY_URL): not_modified('"a"')}),
        now=much_later,
        pause=Pauses(),
    )

    assert report == ScanReport(added=0, closed=0, removed=0, errors=[])
    assert [p.source_key for p in postings(db)] == ["row-1", "row-2"]
    assert all(p.last_seen_at == much_later for p in postings(db))


def test_304_refresh_is_scoped_to_the_list_that_did_not_change(db_session):
    db = db_session
    custom = "https://lists.example.test/custom.json"
    configure(db, list_urls=[SIMPLIFY_URL, custom])
    run_scan(
        db,
        full_http({("GET", custom): json_result([list_row(9)], etag='"c1"')}),
        now=NOW,
        pause=Pauses(),
    )

    later = NOW + timedelta(hours=6)
    run_scan(
        db,
        full_http(
            {
                ("GET", SIMPLIFY_URL): not_modified('"s1"'),
                ("GET", custom): json_result([list_row(9)], etag='"c1"'),
            }
        ),
        now=later,
        pause=Pauses(),
    )

    seen = {(p.source, p.source_key): p.last_seen_at for p in postings(db)}
    assert seen[(PostingSource.SIMPLIFY, "row-1")] == later
    custom_keys = [k for k in seen if k[0] is PostingSource.LIST]
    assert len(custom_keys) == 1
    assert seen[custom_keys[0]] == later


def test_list_that_no_longer_sends_an_etag_forgets_the_old_one_and_dropped_urls_are_pruned(db_session):
    db = db_session
    configure(
        db,
        list_urls=[SIMPLIFY_URL],
        etags={SIMPLIFY_URL: '"old"', "https://raw.githubusercontent.com/gone/list.json": '"x"'},
    )
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([list_row(1)])})

    run_scan(db, http, now=NOW, pause=Pauses())

    assert http.calls[0].etag == '"old"'
    assert settings_service.get_settings(db).discovery_list_etags == {}


def test_closing_and_housekeeping_are_counted(db_session):
    db = db_session
    configure(db, list_urls=[SIMPLIFY_URL])
    run_scan(
        db,
        FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([list_row(1), list_row(2)], etag='"a"')}),
        now=NOW,
        pause=Pauses(),
    )
    # A dismissed board posting no scan has seen for 90 days is removed.
    stale = Posting(
        source=PostingSource.GREENHOUSE,
        source_key="stale",
        company="Old Co",
        title="Intern",
        locations=[],
        url="https://jobs.example.com/stale",
        url_key="jobs.example.com/stale",
        terms=[],
        first_seen_at=NOW - timedelta(days=200),
        last_seen_at=NOW - timedelta(days=100),
        state=PostingState.DISMISSED,
        state_changed_at=NOW - timedelta(days=100),
    )
    db.add(stale)
    db.commit()

    # Row 2 disappears from the list: closed now, deleted only once 90 days
    # have passed without any scan seeing it.
    report = run_scan(
        db,
        FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([list_row(1)], etag='"b"')}),
        now=NOW + timedelta(hours=6),
        pause=Pauses(),
    )

    assert report.closed == 1
    assert report.removed == 1
    assert report.errors == []
    assert [p.source_key for p in postings(db)] == ["row-1", "row-2"]

    report = run_scan(
        db,
        FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([list_row(1)], etag='"c"')}),
        now=NOW + timedelta(days=91),
        pause=Pauses(),
    )

    assert report.removed == 1
    assert [p.source_key for p in postings(db)] == ["row-1"]


def test_workday_board_is_searched_with_the_watchlist_keywords(db_session):
    db = db_session
    configure(db, list_urls=[], keywords=["intern"])
    host = "acme.wd5.myworkdayjobs.com"
    add_company(db, "Acme", WatchAts.WORKDAY, f"{host}/acme/External")
    api = f"https://{host}/wday/cxs/acme/External/jobs"
    http = FakeDiscoveryHttp({("POST", api): json_result({"total": 0, "jobPostings": []})})

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert report.errors == []
    assert [c.body["searchText"] for c in http.calls] == ["intern"]


def test_a_lone_surrogate_in_a_list_row_does_not_fail_the_source(db_session):
    # psycopg cannot encode a lone surrogate: one row carrying one must not
    # fail the whole list on every scan (the good rows still ingest).
    db = db_session
    configure(db, list_urls=[SIMPLIFY_URL])
    rows = [
        list_row(1),
        list_row(2) | {"company_name": "Bad\ud800 Co"},
        list_row(3) | {"url": "https://jobs.example.com/list/\ud800"},
    ]
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result(rows, etag='"a"')})

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert report.errors == []
    assert report.added == 2
    stored = postings(db)
    assert sorted(p.source_key for p in stored) == ["row-1", "row-2"]
    assert next(p.company for p in stored if p.source_key == "row-2") == "Bad Co"
    for posting in stored:
        (posting.company + posting.title + posting.url).encode("utf-8")


def test_a_company_removed_during_the_scan_is_skipped_not_an_error(db_session):
    # The watchlist row is gone by the time its postings are written, so the
    # insert fails on the foreign key: that is a skip, not a scan error.
    db = db_session
    configure(db, list_urls=[])
    acme = add_company(db, "Acme", WatchAts.GREENHOUSE, "acme")
    beta = add_company(db, "Beta", WatchAts.LEVER, "beta")

    def remove_acme_then_answer(call: FakeCall) -> FetchResult:
        watchlist.remove_company(db, acme.id)
        return json_result({"jobs": [gh_job(11)]})

    http = full_http({("GET", GH_API.format(token="acme")): remove_acme_then_answer})

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert report.errors == []
    assert [p.source_key for p in postings(db)] == ["aaa-1"]  # only Beta's
    assert db.get(WatchCompany, acme.id) is None
    db.refresh(beta)
    assert beta.last_checked_at == NOW and beta.last_error is None
    assert settings_service.get_settings(db).last_scan_error is None


def test_a_company_removed_before_its_scan_is_recorded_is_skipped(db_session):
    db = db_session
    configure(db, list_urls=[])
    acme = add_company(db, "Acme", WatchAts.GREENHOUSE, "acme")

    def remove_acme_after_a_failure(call: FakeCall) -> FetchResult:
        # The board answered badly and the company is removed right after, so
        # there is nothing left to record the failure on.
        watchlist.remove_company(db, acme.id)
        raise DiscoveryFetchError("boards-api.greenhouse.io/v1: status 500", status=500)

    http = full_http({("GET", GH_API.format(token="acme")): remove_acme_after_a_failure})

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert report.errors == []
    assert db.get(WatchCompany, acme.id) is None
    assert settings_service.get_settings(db).last_scan_error is None


def test_workday_pages_are_paused_through_the_scans_own_pause(db_session):
    db = db_session
    configure(db, list_urls=[], keywords=["intern", "internship"])
    host = "acme.wd5.myworkdayjobs.com"
    add_company(db, "Acme", WatchAts.WORKDAY, f"{host}/acme/External")
    api = f"https://{host}/wday/cxs/acme/External/jobs"
    page = {
        "total": 21,
        "jobPostings": [
            {
                "title": f"Engineering Intern {n}",
                "externalPath": f"/job/Remote/Engineering-Intern_JR{n}",
                "locationsText": "Remote",
                "postedOn": "Posted Today",
            }
            for n in range(20)
        ],
    }
    http = FakeDiscoveryHttp(
        {("POST", api): [json_result(page), json_result({"total": 0, "jobPostings": []})]}
    )
    pauses = Pauses()

    report = run_scan(db, http, now=NOW, pause=pauses)

    assert report.errors == []
    # "internship" is covered by "intern", so only one search runs, over two
    # pages, with the scan's own pause between them.
    assert [c.body["searchText"] for c in http.calls] == ["intern", "intern"]
    assert pauses.calls == [sources.WORKDAY_PAGE_PAUSE]


# --- one source down ---------------------------------------------------------


def test_failing_sources_are_recorded_while_the_others_ingest(db_session):
    db = db_session
    configure(db, etags={SIMPLIFY_URL: '"s0"'})
    acme = add_company(db, "Acme", WatchAts.GREENHOUSE, "acme")
    beta = add_company(db, "Beta", WatchAts.LEVER, "beta", last_error="old failure")
    gamma = add_company(db, "Gamma", WatchAts.GREENHOUSE, "gamma")
    # A posting the failing list listed before: it must not be closed.
    run_scan(
        db,
        FakeDiscoveryHttp(
            {
                ("GET", SIMPLIFY_URL): json_result([list_row(1)], etag='"s0"'),
                ("GET", VANSHB03_URL): not_modified(),
                ("GET", GH_API.format(token="acme")): json_result({"jobs": [gh_job(11)]}),
                ("GET", LEVER_API.format(token="beta")): json_result([]),
                ("GET", GH_API.format(token="gamma")): json_result({"jobs": []}),
            }
        ),
        now=NOW - timedelta(hours=6),
        pause=Pauses(),
    )

    http = FakeDiscoveryHttp(
        {
            ("GET", SIMPLIFY_URL): DiscoveryFetchError("raw.githubusercontent.com/x: status 500", status=500),
            ("GET", VANSHB03_URL): json_result([list_row(2) | {"source": "vanshb03"}], etag='"v1"'),
            # Not a DiscoveryFetchError: fetch_board lets it through.
            ("GET", GH_API.format(token="acme")): RuntimeError("secret response body"),
            ("GET", LEVER_API.format(token="beta")): json_result([lever_job("aaa-1")]),
            ("GET", GH_API.format(token="gamma")): json_result("not a board"),
        }
    )
    pauses = Pauses()
    report = run_scan(db, http, now=NOW, pause=pauses)

    assert report is not None
    assert report.added == 2  # vanshb03 row + Beta's job
    assert len(report.errors) == 3
    assert report.errors[0].startswith("Simplify list: ")
    assert report.errors[1] == "Acme: unexpected error (RuntimeError)"
    assert report.errors[2].startswith("Gamma: ")
    assert pauses.calls == [1.0, 1.0]

    by_key = {p.source_key: p for p in postings(db)}
    assert by_key["row-1"].closed is False  # failed list closes nothing
    assert by_key["11"].closed is False  # failed board closes nothing
    assert "row-2" in by_key and "aaa-1" in by_key

    s = settings_service.get_settings(db)
    assert s.last_scan_at == NOW
    assert s.last_scan_error == "; ".join(report.errors)
    assert "secret" not in s.last_scan_error
    # The failed list keeps its ETag; the good one stores its new one.
    assert s.discovery_list_etags == {SIMPLIFY_URL: '"s0"', VANSHB03_URL: '"v1"'}

    for company in (acme, beta, gamma):
        db.refresh(company)
        assert company.last_checked_at == NOW
    assert acme.last_error == "Acme: unexpected error (RuntimeError)"
    assert beta.last_error is None  # cleared on success
    assert gamma.last_error.startswith("Gamma: ")


def test_an_unexpected_ingest_failure_is_rolled_back_and_the_scan_continues(db_session, monkeypatch):
    db = db_session
    configure(db)
    real_ingest = scanner.ingest
    calls = []

    def flaky_ingest(session, result, now, **kwargs):
        calls.append(result.name)
        if len(calls) == 1:
            session.add(
                Posting(
                    source=PostingSource.SIMPLIFY,
                    source_key="half-written",
                    company="X",
                    title="Y",
                    locations=[],
                    url="https://jobs.example.com/half",
                    url_key="jobs.example.com/half",
                    terms=[],
                    first_seen_at=now,
                    last_seen_at=now,
                    state_changed_at=now,
                )
            )
            session.flush()
            raise ValueError("boom")
        return real_ingest(session, result, now, **kwargs)

    monkeypatch.setattr(scanner, "ingest", flaky_ingest)
    report = run_scan(db, full_http(), now=NOW, pause=Pauses())

    assert report.errors == ["Simplify list: unexpected error (ValueError)"]
    keys = {p.source_key for p in postings(db)}
    assert "half-written" not in keys
    assert "row-2" in keys
    s = settings_service.get_settings(db)
    # The failed list stores no ETag, so the next scan downloads it again.
    assert s.discovery_list_etags == {VANSHB03_URL: '"v1"'}
    assert s.last_scan_error == "Simplify list: unexpected error (ValueError)"


def test_clean_scan_clears_the_previous_scan_error(db_session):
    db = db_session
    s = configure(db, list_urls=[SIMPLIFY_URL])
    s.last_scan_error = "Simplify list: status 500"
    db.commit()

    run_scan(db, FakeDiscoveryHttp({("GET", SIMPLIFY_URL): not_modified()}), now=NOW, pause=Pauses())

    assert settings_service.get_settings(db).last_scan_error is None


def test_last_scan_error_is_capped(db_session):
    db = db_session
    configure(db, list_urls=[])
    http = FakeDiscoveryHttp()
    for n in range(12):
        token = f"co{n}"
        add_company(db, f"Company {n} " + "x" * 300, WatchAts.GREENHOUSE, token)
        http.add("GET", GH_API.format(token=token), DiscoveryFetchError("down " + "y" * 400))

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert len(report.errors) == 12
    error = settings_service.get_settings(db).last_scan_error
    assert error is not None
    assert len(error) <= LAST_SCAN_ERROR_MAX == 2000
    assert error.startswith(report.errors[0])


def test_scan_with_nothing_configured_still_records_the_scan(db_session):
    db = db_session
    configure(db, list_urls=[])
    http = FakeDiscoveryHttp()

    report = run_scan(db, http, now=NOW, pause=Pauses())

    assert report == ScanReport(added=0, closed=0, removed=0, errors=[])
    assert http.calls == []
    assert settings_service.get_settings(db).last_scan_at == NOW


def test_now_defaults_to_the_current_time(db_session):
    db = db_session
    configure(db, list_urls=[])
    before = datetime.now(UTC)
    run_scan(db, FakeDiscoveryHttp(), pause=Pauses())
    assert before <= settings_service.get_settings(db).last_scan_at <= datetime.now(UTC)


# --- single flight -----------------------------------------------------------


def test_scan_returns_none_and_writes_nothing_while_another_scan_holds_the_lock(
    db_session, other_connection
):
    db = db_session
    configure(db)
    add_company(db, "Acme", WatchAts.GREENHOUSE, "acme")
    assert try_lock(other_connection)
    http = full_http()
    pauses = Pauses()

    assert run_scan(db, http, now=NOW, pause=pauses) is None

    assert http.calls == []
    assert pauses.calls == []
    assert postings(db) == []
    s = settings_service.get_settings(db)
    db.refresh(s)
    assert s.last_scan_at is None
    assert s.discovery_list_etags == {}


def test_lock_is_held_for_the_whole_scan_across_commits_and_released_after(
    db_session, other_connection
):
    db = db_session
    configure(db)
    seen = []

    def second_list(call: FakeCall) -> FetchResult:
        # The first list was already ingested (and committed) by now.
        seen.append((try_lock(other_connection), scan_status(db)["scanning"]))
        return json_result([list_row(2) | {"source": "vanshb03"}])

    http = full_http({("GET", VANSHB03_URL): second_list})
    run_scan(db, http, now=NOW, pause=Pauses())

    assert seen == [(False, True)]
    assert try_lock(other_connection)  # released at the end
    assert unlock(other_connection)
    assert scan_status(db)["scanning"] is False


def test_lock_is_released_when_the_scan_raises(db_session, other_connection, monkeypatch):
    db = db_session

    def broken(session):
        raise RuntimeError("database went away")

    monkeypatch.setattr(scanner, "get_settings", broken)
    with pytest.raises(RuntimeError):
        run_scan(db, FakeDiscoveryHttp(), now=NOW, pause=Pauses())

    assert try_lock(other_connection)


# --- status ------------------------------------------------------------------


def test_scan_status_reports_the_last_scan_and_inbox_count(db_session):
    db = db_session
    configure(db)
    run_scan(
        db,
        full_http(
            {
                ("GET", SIMPLIFY_URL): json_result(
                    [list_row(1), list_row(3, title="Senior Software Engineer")]
                ),
                ("GET", VANSHB03_URL): DiscoveryFetchError("down"),
            }
        ),
        now=NOW,
        pause=Pauses(),
    )

    status = scan_status(db)

    assert status == {
        "last_scan_at": NOW,
        "last_scan_error": "vanshb03 list: down",
        "scanning": False,
        # The default exclude keywords hide "Senior ..." from the Inbox.
        "inbox_count": 1,
    }


def test_is_scan_running_reads_pg_locks_without_taking_the_lock(db_session, _engine):
    # Taking the lock even for an instant (the old check did) makes a scan
    # that starts at that moment skip itself, so the check must be read-only.
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(_engine, "before_cursor_execute", record)
    try:
        assert is_scan_running(db_session) is False
    finally:
        event.remove(_engine, "before_cursor_execute", record)

    assert statements, "the check ran no SQL at all"
    assert any("pg_locks" in sql for sql in statements)
    assert not any("advisory" in sql.lower() and "pg_locks" not in sql for sql in statements)


def test_is_scan_running_sees_a_real_held_lock_and_leaves_it_alone(
    db_session, other_connection
):
    assert try_lock(other_connection)

    assert is_scan_running(db_session) is True
    assert is_scan_running(db_session) is True
    # Not ours to release: the holder still has it.
    assert unlock(other_connection) is True

    assert is_scan_running(db_session) is False
    assert try_lock(other_connection)  # nothing of ours is in the way


def test_is_scan_running_ignores_another_advisory_lock(db_session, other_connection):
    other_key = SCAN_LOCK_KEY + 1
    assert other_connection.execute(
        text("SELECT pg_try_advisory_lock(:k)"), {"k": other_key}
    ).scalar_one()
    try:
        assert is_scan_running(db_session) is False
    finally:
        other_connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": other_key})


def test_scan_status_reports_scanning_while_the_lock_is_held_and_leaves_it_held(
    db_session, other_connection
):
    assert try_lock(other_connection)

    assert scan_status(db_session)["scanning"] is True
    assert scan_status(db_session)["scanning"] is True
    # Still held by the other connection; scan_status released nothing of its own.
    assert unlock(other_connection) is True
    assert scan_status(db_session)["scanning"] is False
    # And scan_status does not leave the lock held either.
    assert try_lock(other_connection)


# --- daily re-score (Phase 5 spec §4) ----------------------------------------


def _stale_posting(db) -> Posting:
    """An Inbox posting no source lists, with a score from long ago."""
    posting = Posting(
        source=PostingSource.LIST,
        source_key="https://x.test/list.json:old",
        company="Old Co",
        title="Backend Intern",
        locations=[],
        url="https://jobs.example.com/old",
        url_key="https://jobs.example.com/old",
        terms=[],
        date_posted=NOW - timedelta(days=2),
        first_seen_at=NOW - timedelta(days=2),
        last_seen_at=NOW - timedelta(days=2),
        state=PostingState.NEW,
        local_score=99,
    )
    db.add(posting)
    db.commit()
    return posting


def test_first_scan_of_the_day_rescores_every_posting(db_session):
    db = db_session
    s = configure(db, list_urls=())
    s.ranking_role_keywords = ["backend"]
    s.last_scan_at = NOW - timedelta(days=1)
    db.commit()
    posting = _stale_posting(db)

    run_scan(db, FakeDiscoveryHttp({}), now=NOW, pause=Pauses())
    db.refresh(posting)
    assert (posting.local_score, posting.local_reasons) == (50, ["Title matches 'backend'", "posted in the last 3 days"])

    # Later the same day: no full pass (ingest still scores what it touches).
    posting.local_score = 99
    db.commit()
    run_scan(db, FakeDiscoveryHttp({}), now=NOW + timedelta(hours=6), pause=Pauses())
    db.refresh(posting)
    assert posting.local_score == 99


def test_the_very_first_scan_rescores_too(db_session):
    db = db_session
    configure(db, list_urls=())
    posting = _stale_posting(db)
    run_scan(db, FakeDiscoveryHttp({}), now=NOW, pause=Pauses())
    db.refresh(posting)
    assert posting.local_score == 50


def test_scanned_list_rows_are_scored(db_session):
    db = db_session
    s = configure(db, list_urls=(SIMPLIFY_URL,))
    s.ranking_role_keywords = ["software engineer"]
    db.commit()
    run_scan(db, FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([list_row(1)])}), now=NOW, pause=Pauses())
    (row,) = postings(db)
    assert row.local_score >= 40
    assert row.local_reasons[0] == "Title matches 'software engineer'"
