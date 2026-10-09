"""/api/discovery routes (Phase 2 plan Task 9).

HTTP goes through the `discovery_http` fake and Scan now's background task
runs in the test session (both from tests/api/conftest.py), so nothing here
touches the network or commits outside the test transaction.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.models.application import Application
from app.models.posting import Posting, PostingSource, PostingState
from app.models.research_queue import ResearchQueueItem
from app.models.watch_company import WatchCompany
from app.services import settings_service
from app.services.discovery.http import DiscoveryFetchError
from app.services.discovery.scanner import SCAN_LOCK_KEY
from app.services.discovery.urls import normalize_url
from app.services.nudges import utc_today
from tests.services.discovery.fakes import json_result, page_result

SAVED_TAB = "Saved postings"
EARLIER = datetime.now(UTC) - timedelta(days=3)

GH_JOB_URL = "https://job-boards.greenhouse.io/acme/jobs/4012345"
GH_JOB_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345"
LIST_URL = "https://raw.githubusercontent.com/example/list/dev/listings.json"

ROUTES = [
    ("GET", "/api/discovery/postings"),
    ("POST", "/api/discovery/postings/1/save"),
    ("POST", "/api/discovery/postings/1/dismiss"),
    ("POST", "/api/discovery/postings/1/restore"),
    ("POST", "/api/discovery/postings/1/apply"),
    ("POST", "/api/discovery/postings/dismiss-all"),
    ("POST", "/api/discovery/paste/preview"),
    ("POST", "/api/discovery/paste"),
    ("GET", "/api/discovery/watchlist"),
    ("POST", "/api/discovery/watchlist"),
    ("DELETE", "/api/discovery/watchlist/1"),
    ("POST", "/api/discovery/scan"),
    ("GET", "/api/discovery/status"),
    ("POST", "/api/discovery/match-count"),
    ("POST", "/api/discovery/top-picks-count"),
]


def make_posting(
    db,
    key: str = "1",
    *,
    state: PostingState = PostingState.NEW,
    source: PostingSource = PostingSource.SIMPLIFY,
    company: str = "Acme",
    title: str = "Software Engineer Intern",
    locations: list[str] | None = None,
    url: str | None = None,
    changed: datetime = EARLIER,
    watch_company_id: int | None = None,
    **extra,
) -> Posting:
    url = url or f"https://jobs.example.com/{source.value}/{key}"
    posting = Posting(
        source=source,
        source_key=key,
        company=company,
        title=title,
        locations=locations if locations is not None else ["New York, NY", "Remote"],
        url=url,
        url_key=normalize_url(url),
        terms=["Summer 2027"],
        category="Software",
        state=state,
        state_changed_at=changed,
        first_seen_at=EARLIER,
        last_seen_at=EARLIER,
        closed=False,
        watch_company_id=watch_company_id,
        **extra,
    )
    db.add(posting)
    db.commit()
    return posting


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


@pytest.fixture()
def other_connection(_engine):
    """A second database session, standing in for a running scan."""
    conn = _engine.connect()
    yield conn
    conn.execute(text("SELECT pg_advisory_unlock_all()"))
    conn.rollback()
    conn.close()


def hold_scan_lock(conn) -> None:
    assert conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCAN_LOCK_KEY}).scalar_one()


# --- auth --------------------------------------------------------------------


def test_routes_list_covers_every_discovery_route():
    # The auth and Claude-token boundary tests walk ROUTES; keep it complete.
    from app.api.discovery import router

    served = {
        (method, route.path.replace("{posting_id}", "1").replace("{company_id}", "1"))
        for route in router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert served == set(ROUTES)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_a_session(client, method, path):
    r = client.request(method, path, json={})
    assert r.status_code == 401


# --- listing -----------------------------------------------------------------


def test_inbox_lists_filtered_new_postings_with_a_total(logged_in_client, db_session):
    shown = make_posting(db_session, "1")
    make_posting(db_session, "2", title="Senior Software Engineer")  # excluded keyword
    make_posting(db_session, "3", state=PostingState.SAVED)

    r = logged_in_client.get("/api/discovery/postings")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [p["id"] for p in body["items"]] == [shown.id]
    item = body["items"][0]
    assert item["company"] == "Acme"
    assert item["title"] == "Software Engineer Intern"
    assert item["locations"] == ["New York, NY", "Remote"]
    assert item["source"] == "simplify"
    assert item["state"] == "new"
    assert item["closed"] is False
    assert "source_key" not in item and "url_key" not in item


def test_saved_and_dismissed_views(logged_in_client, db_session):
    make_posting(db_session, "1")
    saved = make_posting(db_session, "2", state=PostingState.SAVED)
    dismissed = make_posting(db_session, "3", state=PostingState.DISMISSED)

    r = logged_in_client.get("/api/discovery/postings", params={"view": "saved"})
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["items"]] == [saved.id]
    r = logged_in_client.get("/api/discovery/postings", params={"view": "dismissed"})
    assert [p["id"] for p in r.json()["items"]] == [dismissed.id]
    assert r.json()["total"] == 1


def test_paging(logged_in_client, db_session):
    ids = [
        make_posting(db_session, str(n), state=PostingState.SAVED, changed=EARLIER + timedelta(minutes=n)).id
        for n in range(5)
    ]
    newest_first = list(reversed(ids))

    r = logged_in_client.get("/api/discovery/postings", params={"view": "saved", "limit": 2, "offset": 1})

    assert r.status_code == 200
    assert [p["id"] for p in r.json()["items"]] == newest_first[1:3]
    assert r.json()["total"] == 5


@pytest.mark.parametrize(
    "params",
    [
        {"view": "applied"},
        {"view": ""},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": "x"},
        {"sort": "score"},
        {"min_score": -1},
        {"min_score": 101},
        {"min_score": "high"},
    ],
)
def test_bad_listing_params_are_422(logged_in_client, params):
    assert logged_in_client.get("/api/discovery/postings", params=params).status_code == 422


def test_listing_limit_bounds_are_inclusive(logged_in_client):
    for limit in (1, 100):
        assert logged_in_client.get("/api/discovery/postings", params={"limit": limit}).status_code == 200


# --- state changes -----------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "start", "end"),
    [
        ("save", PostingState.NEW, "saved"),
        ("save", PostingState.DISMISSED, "saved"),
        ("dismiss", PostingState.NEW, "dismissed"),
        ("dismiss", PostingState.SAVED, "dismissed"),
        ("restore", PostingState.DISMISSED, "new"),
    ],
)
def test_state_changes_return_the_posting_and_schedule_a_sync(
    logged_in_client, db_session, sheet_sync_recorder, action, start, end
):
    posting = make_posting(db_session, state=start)

    r = logged_in_client.post(f"/api/discovery/postings/{posting.id}/{action}")

    assert r.status_code == 200
    assert r.json()["id"] == posting.id
    assert r.json()["state"] == end
    db_session.refresh(posting)
    assert posting.state.value == end
    assert sheet_sync_recorder.scheduled == [[SAVED_TAB]]


@pytest.mark.parametrize(
    ("action", "start", "detail"),
    [
        ("save", PostingState.SAVED, "already saved"),
        ("dismiss", PostingState.DISMISSED, "already dismissed"),
        ("restore", PostingState.NEW, "can't restore a posting that is new"),
        ("restore", PostingState.SAVED, "can't restore a posting that is saved"),
    ],
)
def test_invalid_state_change_is_409_and_schedules_nothing(
    logged_in_client, db_session, sheet_sync_recorder, action, start, detail
):
    posting = make_posting(db_session, state=start)

    r = logged_in_client.post(f"/api/discovery/postings/{posting.id}/{action}")

    assert r.status_code == 409
    assert r.json() == {"detail": detail}
    assert sheet_sync_recorder.scheduled == []


@pytest.mark.parametrize("action", ["save", "dismiss", "restore", "apply"])
def test_action_on_a_missing_posting_is_404(logged_in_client, sheet_sync_recorder, action):
    r = logged_in_client.post(f"/api/discovery/postings/999999/{action}")
    assert r.status_code == 404
    assert r.json() == {"detail": "posting not found"}
    assert sheet_sync_recorder.scheduled == []


def test_apply_creates_an_applied_application_and_syncs_both_tabs(
    logged_in_client, db_session, sheet_sync_recorder
):
    posting = make_posting(db_session, state=PostingState.SAVED, company="Stripe", title="SWE Intern")

    r = logged_in_client.post(f"/api/discovery/postings/{posting.id}/apply")

    assert r.status_code == 201
    body = r.json()
    assert body["company"] == "Stripe"
    assert body["role_title"] == "SWE Intern"
    assert body["status"] == "applied"
    assert body["date_applied"] == utc_today().isoformat()
    assert body["location"] == "New York, NY"
    assert body["job_link"] == posting.url
    assert body["source"] == "Discover: Simplify"
    assert body["archived"] is False and isinstance(body["id"], int)
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED
    assert posting.application_id == body["id"]
    assert sheet_sync_recorder.scheduled == [["Applications", SAVED_TAB]]


def test_apply_twice_is_409_with_one_application(logged_in_client, db_session, sheet_sync_recorder):
    posting = make_posting(db_session)
    assert logged_in_client.post(f"/api/discovery/postings/{posting.id}/apply").status_code == 201

    r = logged_in_client.post(f"/api/discovery/postings/{posting.id}/apply")

    assert r.status_code == 409
    assert r.json() == {"detail": "already applied"}
    assert count(db_session, Application) == 1
    assert count(db_session, ResearchQueueItem) == 1
    assert len(sheet_sync_recorder.scheduled) == 1


def test_dismiss_all_dismisses_only_new_postings(logged_in_client, db_session, sheet_sync_recorder):
    a = make_posting(db_session, "1")
    b = make_posting(db_session, "2")
    saved = make_posting(db_session, "3", state=PostingState.SAVED)

    r = logged_in_client.post(
        "/api/discovery/postings/dismiss-all", json={"ids": [a.id, b.id, saved.id, 999999]}
    )

    assert r.status_code == 200
    assert r.json() == {"dismissed": 2}
    for posting, state in ((a, PostingState.DISMISSED), (b, PostingState.DISMISSED), (saved, PostingState.SAVED)):
        db_session.refresh(posting)
        assert posting.state is state
    assert sheet_sync_recorder.scheduled == [[SAVED_TAB]]


@pytest.mark.parametrize("body", [{}, {"ids": "1"}, {"ids": list(range(501))}])
def test_dismiss_all_validates_its_body(logged_in_client, sheet_sync_recorder, body):
    assert logged_in_client.post("/api/discovery/postings/dismiss-all", json=body).status_code == 422
    assert sheet_sync_recorder.scheduled == []


# --- paste a link ------------------------------------------------------------


def gh_job() -> dict:
    return {
        "id": 4012345,
        "title": "Software Engineering Intern",
        "company_name": "Acme Robotics",
        "location": {"name": "Boston, MA"},
        "first_published": "2026-10-01T09:00:00-04:00",
        "absolute_url": GH_JOB_URL,
    }


def test_paste_preview_returns_editable_details_and_writes_nothing(
    logged_in_client, db_session, discovery_http, sheet_sync_recorder
):
    discovery_http.add("GET", GH_JOB_API, json_result(gh_job()))

    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": GH_JOB_URL})

    assert r.status_code == 200
    assert r.json() == {
        "company": "Acme Robotics",
        "title": "Software Engineering Intern",
        "locations": ["Boston, MA"],
        "url": GH_JOB_URL,
        "date_posted": "2026-10-01T13:00:00Z",
        "source": "greenhouse",
    }
    assert count(db_session, Posting) == 0
    assert sheet_sync_recorder.scheduled == []


def test_paste_preview_fetch_error_is_422_with_the_message(logged_in_client, discovery_http):
    url = "https://careers.globex.example/jobs/77"
    discovery_http.add("PAGE", url, DiscoveryFetchError("careers.globex.example: HTTP 404", status=404))

    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": url})

    assert r.status_code == 422
    assert r.json() == {"detail": "Couldn't read that page (status 404)"}


def test_paste_preview_of_a_page_without_job_data_leaves_fields_to_fill(logged_in_client, discovery_http):
    url = "https://careers.globex.example/jobs/77"
    discovery_http.add("PAGE", url, page_result("<html><body>secret body text</body></html>", url=url))

    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": url})

    assert r.status_code == 200
    assert r.json()["title"] == "" and r.json()["locations"] == []
    assert r.json()["source"] == "pasted"
    assert "secret body text" not in r.text


def test_paste_preview_of_a_page_with_a_lone_surrogate_in_its_json_ld(
    logged_in_client, discovery_http
):
    # A lone surrogate anywhere in the page must not reach the response (it
    # cannot be encoded as UTF-8, so it would break the whole request).
    url = "https://careers.globex.example/jobs/88"
    page = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "SWE Intern\\ud800",'
        ' "hiringOrganization": {"name": "Globex\\ud800"},'
        ' "jobLocation": {"address": {"addressLocality": "New\\ud800 York"}}}'
        "</script></head><body></body></html>"
    )
    discovery_http.add("PAGE", url, page_result(page, url=url))

    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": url})

    assert r.status_code == 200
    assert r.json() == {
        "company": "Globex",
        "title": "SWE Intern",
        "locations": ["New York"],
        "url": url,
        "date_posted": None,
        "source": "pasted",
    }


@pytest.mark.parametrize("url", ["javascript:alert(1)", "not a url", ""])
def test_paste_preview_of_a_non_web_link_is_422_without_a_request(logged_in_client, discovery_http, url):
    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": url})
    assert r.status_code == 422
    assert r.json() == {"detail": "That isn't a web link: it must start with http or https"}
    assert discovery_http.calls == []


def test_paste_preview_of_a_saved_posting_is_409(logged_in_client, db_session, discovery_http):
    posting = make_posting(db_session, state=PostingState.SAVED)

    r = logged_in_client.post("/api/discovery/paste/preview", json={"url": posting.url})

    assert r.status_code == 409
    assert r.json() == {"detail": "already saved"}
    assert discovery_http.calls == []


def test_paste_confirm_saves_the_posting(logged_in_client, db_session, sheet_sync_recorder):
    r = logged_in_client.post(
        "/api/discovery/paste",
        json={
            "url": GH_JOB_URL,
            "company": "Acme Robotics",
            "title": "Software Engineering Intern",
            "locations": ["Boston, MA"],
            "date_posted": "2026-10-01T13:00:00Z",
        },
    )

    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "saved"
    assert body["source"] == "greenhouse"
    assert body["company"] == "Acme Robotics"
    assert body["url"] == GH_JOB_URL
    assert count(db_session, Posting) == 1
    assert sheet_sync_recorder.scheduled == [[SAVED_TAB]]


def test_paste_confirm_of_an_applied_posting_is_409(logged_in_client, db_session, sheet_sync_recorder):
    posting = make_posting(db_session)
    logged_in_client.post(f"/api/discovery/postings/{posting.id}/apply")
    sheet_sync_recorder.scheduled.clear()

    r = logged_in_client.post(
        "/api/discovery/paste", json={"url": posting.url, "company": "Acme", "title": "Intern"}
    )

    assert r.status_code == 409
    assert r.json() == {"detail": "already applied"}
    assert sheet_sync_recorder.scheduled == []


@pytest.mark.parametrize(
    "body",
    [
        {"url": "javascript:alert(1)", "company": "A", "title": "B"},
        {"url": GH_JOB_URL, "company": "", "title": "B"},
        {"url": GH_JOB_URL, "company": "A", "title": "x" * 301},
        {"url": GH_JOB_URL, "company": "A", "title": "B", "locations": [f"City {n}" for n in range(21)]},
    ],
)
def test_paste_confirm_validates_its_body(logged_in_client, db_session, sheet_sync_recorder, body):
    assert logged_in_client.post("/api/discovery/paste", json=body).status_code == 422
    assert count(db_session, Posting) == 0
    assert sheet_sync_recorder.scheduled == []


# --- watchlist ---------------------------------------------------------------


def test_watchlist_add_list_and_remove(logged_in_client, db_session, sheet_sync_recorder):
    r = logged_in_client.post(
        "/api/discovery/watchlist", json={"careers_url": "https://boards.greenhouse.io/openai?gh_src=x"}
    )
    assert r.status_code == 201
    added = r.json()
    assert added["name"] == "Openai"
    assert added["ats"] == "greenhouse"
    assert added["board_token"] == "openai"
    assert added["careers_url"] == "https://job-boards.greenhouse.io/openai"
    assert added["open_matches"] == 0
    assert added["last_checked_at"] is None and added["last_error"] is None

    make_posting(db_session, "1", source=PostingSource.GREENHOUSE, watch_company_id=added["id"])
    make_posting(db_session, "2", source=PostingSource.GREENHOUSE, watch_company_id=added["id"],
                 state=PostingState.SAVED)
    r = logged_in_client.get("/api/discovery/watchlist")
    assert r.status_code == 200
    assert [(c["id"], c["open_matches"]) for c in r.json()] == [(added["id"], 1)]

    r = logged_in_client.delete(f"/api/discovery/watchlist/{added['id']}")
    assert r.status_code == 204
    assert logged_in_client.get("/api/discovery/watchlist").json() == []
    # The saved posting stays; the new one goes, since no scan lists it now.
    assert count(db_session, Posting) == 1
    assert db_session.scalars(select(Posting)).one().state is PostingState.SAVED
    r = logged_in_client.delete(f"/api/discovery/watchlist/{added['id']}")
    assert r.status_code == 404
    assert r.json() == {"detail": "watched company not found"}
    assert sheet_sync_recorder.scheduled == []


def test_watchlist_add_uses_the_given_name(logged_in_client):
    r = logged_in_client.post(
        "/api/discovery/watchlist", json={"careers_url": "https://jobs.lever.co/palantir", "name": "Palantir Tech"}
    )
    assert r.status_code == 201 and r.json()["name"] == "Palantir Tech"


def test_watchlist_duplicate_is_409(logged_in_client):
    body = {"careers_url": "https://jobs.ashbyhq.com/ramp"}
    assert logged_in_client.post("/api/discovery/watchlist", json=body).status_code == 201
    r = logged_in_client.post("/api/discovery/watchlist", json={"careers_url": "https://jobs.ashbyhq.com/RAMP"})
    assert r.status_code == 409
    assert r.json() == {"detail": "that company is already on the watchlist"}


def test_watchlist_custom_site_is_422_with_the_service_message(logged_in_client, db_session):
    r = logged_in_client.post("/api/discovery/watchlist", json={"careers_url": "https://careers.google.com/jobs"})
    assert r.status_code == 422
    assert r.json() == {
        "detail": "Google uses its own careers site, so it can't be watched. Its internships come in "
        "through the community lists, and you can paste any of its postings."
    }
    assert count(db_session, WatchCompany) == 0


def test_watchlist_unknown_site_is_422_with_the_generic_message(logged_in_client):
    r = logged_in_client.post("/api/discovery/watchlist", json={"careers_url": "https://careers.example.org/"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("That careers page isn't on Greenhouse, Lever, Ashby or Workday")


@pytest.mark.parametrize("body", [{}, {"careers_url": "https://jobs.lever.co/x", "name": "n" * 201}])
def test_watchlist_add_validates_its_body(logged_in_client, body):
    assert logged_in_client.post("/api/discovery/watchlist", json=body).status_code == 422


# --- scan --------------------------------------------------------------------


def list_row(n: int) -> dict:
    return {
        "source": "Simplify",
        "category": "Software",
        "company_name": f"List Co {n}",
        "id": f"row-{n}",
        "title": "Software Engineer Intern",
        "active": True,
        "terms": ["Summer 2027"],
        "date_posted": 1775081547,
        "url": f"https://jobs.example.com/list/{n}",
        "locations": ["Remote"],
        "is_visible": True,
        "sponsorship": "Other",
    }


def configure_one_list(db) -> None:
    s = settings_service.get_settings(db)
    s.discovery_list_urls = [LIST_URL]
    db.commit()


def test_scan_starts_a_background_scan_with_the_discovery_http(
    logged_in_client, db_session, discovery_http
):
    configure_one_list(db_session)
    discovery_http.add("GET", LIST_URL, json_result([list_row(1), list_row(2)], etag='"e1"'))

    r = logged_in_client.post("/api/discovery/scan")

    # TestClient runs the background task before returning.
    assert r.status_code == 202
    assert r.json() == {"started": True}
    assert [(c.method, c.url) for c in discovery_http.calls] == [("GET", LIST_URL)]
    assert count(db_session, Posting) == 2
    s = settings_service.get_settings(db_session)
    db_session.refresh(s)
    assert s.last_scan_at is not None
    assert s.last_scan_error is None

    status = logged_in_client.get("/api/discovery/status").json()
    assert status["scanning"] is False
    assert status["inbox_count"] == 2


def test_scan_while_a_scan_runs_is_409_and_does_nothing(
    logged_in_client, db_session, discovery_http, other_connection
):
    configure_one_list(db_session)
    hold_scan_lock(other_connection)

    r = logged_in_client.post("/api/discovery/scan")

    assert r.status_code == 409
    assert r.json() == {"detail": "already scanning"}
    assert discovery_http.calls == []
    assert count(db_session, Posting) == 0


def test_a_failing_background_scan_is_logged_not_raised(
    logged_in_client, db_session, monkeypatch, caplog
):
    from app.api import discovery as discovery_api

    def broken(db, http):
        raise RuntimeError("database went away")

    monkeypatch.setattr(discovery_api, "run_scan", broken)

    r = logged_in_client.post("/api/discovery/scan")

    assert r.status_code == 202
    assert "scan failed" in caplog.text


# --- status and match count ---------------------------------------------------


def test_status_reports_the_last_scan_and_inbox_count(logged_in_client, db_session):
    make_posting(db_session, "1")
    make_posting(db_session, "2", title="Staff Engineer")
    s = settings_service.get_settings(db_session)
    s.last_scan_at = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    s.last_scan_error = "vanshb03 list: down"
    db_session.commit()

    r = logged_in_client.get("/api/discovery/status")

    assert r.status_code == 200
    assert r.json() == {
        "last_scan_at": "2026-10-08T12:00:00Z",
        "last_scan_error": "vanshb03 list: down",
        "scanning": False,
        "inbox_count": 1,
    }


def test_status_reports_scanning_while_the_lock_is_held(logged_in_client, other_connection):
    hold_scan_lock(other_connection)
    assert logged_in_client.get("/api/discovery/status").json()["scanning"] is True


def test_match_count_uses_the_unsaved_filters_in_the_body(logged_in_client, db_session):
    make_posting(db_session, "1", title="Software Engineer Intern")
    make_posting(db_session, "2", title="Senior Data Intern")
    make_posting(db_session, "3", title="Hardware Intern")

    assert logged_in_client.post("/api/discovery/match-count", json={}).json() == {"count": 3}
    r = logged_in_client.post(
        "/api/discovery/match-count",
        json={"discovery_exclude_keywords": ["senior"], "discovery_include_keywords": ["intern"]},
    )
    assert r.status_code == 200
    assert r.json() == {"count": 2}
    r = logged_in_client.post("/api/discovery/match-count", json={"discovery_include_keywords": ["software"]})
    assert r.json() == {"count": 1}


def test_match_count_validates_its_body(logged_in_client):
    r = logged_in_client.post("/api/discovery/match-count", json={"discovery_terms": "Summer 2027"})
    assert r.status_code == 422



# --- ranking (Phase 5 spec §6) -----------------------------------------------


def test_inbox_sorts_by_best_match_or_newest_and_filters_top_picks(logged_in_client, db_session):
    top = make_posting(db_session, "1", local_score=88, local_reasons=["Title matches 'software'"])
    claude = make_posting(db_session, "2", local_score=10, claude_score=75, claude_note="Good fit")
    low = make_posting(db_session, "3", local_score=30)
    newest = make_posting(db_session, "4", local_score=5, date_posted=datetime.now(UTC))

    body = logged_in_client.get("/api/discovery/postings").json()
    assert [p["id"] for p in body["items"]] == [top.id, claude.id, low.id, newest.id]
    assert body["total"] == 4 and body["top_picks"] == 2
    item = body["items"][0]
    assert item["local_score"] == 88 and item["local_reasons"] == ["Title matches 'software'"]
    assert item["claude_score"] is None and item["claude_scored_at"] is None and item["claude_stale"] is False

    body = logged_in_client.get("/api/discovery/postings", params={"sort": "newest"}).json()
    assert body["items"][0]["id"] == newest.id

    body = logged_in_client.get("/api/discovery/postings", params={"min_score": 70}).json()
    assert [p["id"] for p in body["items"]] == [top.id, claude.id]
    assert body["total"] == 2 and body["top_picks"] == 2

    saved = logged_in_client.get("/api/discovery/postings", params={"view": "saved"}).json()
    assert saved["top_picks"] is None


def test_claude_scores_older_than_the_preferences_are_marked_stale(logged_in_client, db_session):
    changed = datetime.now(UTC) - timedelta(hours=1)
    s = settings_service.get_settings(db_session)
    s.ranking_updated_at = changed
    db_session.commit()
    fresh = make_posting(db_session, "1", claude_score=80, claude_scored_at=changed + timedelta(minutes=1))
    stale = make_posting(db_session, "2", claude_score=70, claude_scored_at=changed - timedelta(minutes=1))
    legacy = make_posting(db_session, "3", claude_score=60)  # scored before the timestamp existed
    unscored = make_posting(db_session, "4", local_score=50)

    items = {p["id"]: p for p in logged_in_client.get("/api/discovery/postings").json()["items"]}
    assert items[fresh.id]["claude_stale"] is False
    assert items[stale.id]["claude_stale"] is True
    assert items[legacy.id]["claude_stale"] is True
    assert items[unscored.id]["claude_stale"] is False

    r = logged_in_client.post(f"/api/discovery/postings/{stale.id}/save")
    assert r.status_code == 200 and r.json()["claude_stale"] is True


def test_top_picks_count_uses_the_unsaved_preferences_in_the_body(logged_in_client, db_session):
    make_posting(db_session, "1", title="Backend Engineer Intern", locations=["New York, NY"])
    make_posting(db_session, "2", title="Frontend Intern", claude_score=90)
    make_posting(db_session, "3", title="Senior Backend Engineer")  # not in the Inbox

    assert logged_in_client.post("/api/discovery/top-picks-count", json={}).json() == {"count": 1}
    r = logged_in_client.post(
        "/api/discovery/top-picks-count",
        json={
            "ranking_role_keywords": ["backend"],
            "ranking_skill_keywords": ["engineer", "intern"],
            "ranking_preferred_locations": ["New York"],
        },
    )
    # 40 (role) + 10 (two skills) + 15 (location) + freshness: a Top pick.
    assert r.status_code == 200 and r.json() == {"count": 2}
    # Nothing was saved.
    assert settings_service.get_settings(db_session).ranking_role_keywords == []


def test_top_picks_count_validates_its_body(logged_in_client):
    assert logged_in_client.post("/api/discovery/top-picks-count", json={"ranking_role_keywords": "ml"}).status_code == 422
    r = logged_in_client.post("/api/discovery/top-picks-count", json={"ranking_role_keywords": ["x" * 61]})
    assert r.status_code == 422
