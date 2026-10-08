"""End-to-end job discovery through the API (Phase 2 plan Task 15).

Default settings, a watched Greenhouse board, Scan now, the Inbox, save,
apply, a re-scan that closes postings, then paste a link. Only fakes: the
autouse `discovery_http` fixture serves the recorded fixtures in
`tests/fixtures/discovery/`, so the real parsers, ingest, filters and
actions all run and nothing touches the network.
"""

import copy
import json
from pathlib import Path

from sqlalchemy import select

from app.models.app_settings import DEFAULT_LIST_URLS
from app.models.application import Application
from app.models.posting import Posting, PostingSource, PostingState
from app.models.research_queue import QueueKind, ResearchQueueItem
from app.services import settings_service
from app.services.nudges import utc_today
from tests.services.discovery.fakes import json_result, page_result

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"
SIMPLIFY_URL, VANSHB03_URL = DEFAULT_LIST_URLS
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/acmerobotics/jobs"
PASTED_URL = "https://careers.globex.example/jobs/swe-intern-2027"

MELIUS_ID = "56196707-1bc1-44de-9e0e-a32456792771"
TIKTOK_ID = "0774f31a-26bd-433d-bc51-3d4bbb820b0d"

LONG_TITLE = "Software Engineer Intern " + "A" * 275  # the 50 KB title, cut to 300

# What default settings let through from the three sources.
EXPECTED_INBOX = {
    ("simplify", "Aquatic Capital Management", "Software Engineer Intern"),
    ("simplify", "Aquatic Capital Management", LONG_TITLE),
    ("simplify", "Steven's Capital Management", "Software Engineer"),
    ("simplify", "TikTok", "Research Scientist Intern - TikTok Search / Generative AI - LLM"),
    ("simplify", "Melius", "Software Engineer Intern"),
    ("vanshb03", "Point72", "Investment Analyst Intern, Point72 Academy"),
    ("vanshb03", "Point72", LONG_TITLE),
    ("vanshb03", "Dedalus Labs", "Forward Deployed Engineer Intern"),
    ("vanshb03", "AMD", "Software Engineer Intern"),
    ("greenhouse", "Acme Robotics", "Software Engineering Intern, Summer 2027"),
    ("greenhouse", "Acme Robotics", "Machine Learning Intern"),
}


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def inbox(client) -> list[dict]:
    r = client.get("/api/discovery/postings", params={"view": "inbox", "limit": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["items"])
    return body["items"]


def find(items: list[dict], company: str, title: str) -> dict:
    [item] = [p for p in items if p["company"] == company and p["title"] == title]
    return item


def test_scan_save_apply_close_and_paste(logged_in_client, db_session, discovery_http):
    client = logged_in_client
    simplify = fixture("simplify_listings.json")
    discovery_http.add("GET", SIMPLIFY_URL, json_result(simplify, url=SIMPLIFY_URL, etag='"s1"'))
    vanshb03 = fixture("vanshb03_listings.json")
    discovery_http.add("GET", VANSHB03_URL, json_result(vanshb03, url=VANSHB03_URL))
    board = fixture("greenhouse_board.json")
    discovery_http.add("GET", GREENHOUSE_API, json_result(board, url=GREENHOUSE_API))

    # Settings are the defaults: the two community lists, Summer 2027, Software + AI/ML/Data.
    s = settings_service.get_settings(db_session)
    assert s.discovery_list_urls == list(DEFAULT_LIST_URLS)

    # 1. Watch a company on Greenhouse.
    r = client.post(
        "/api/discovery/watchlist",
        json={"careers_url": "https://job-boards.greenhouse.io/acmerobotics", "name": "Acme Robotics"},
    )
    assert r.status_code == 201
    watch_id = r.json()["id"]
    assert r.json()["ats"] == "greenhouse" and r.json()["board_token"] == "acmerobotics"

    # 2. Scan now (TestClient runs the background task before returning).
    r = client.post("/api/discovery/scan")
    assert r.status_code == 202
    assert [(c.method, c.url) for c in discovery_http.calls] == [
        ("GET", SIMPLIFY_URL),
        ("GET", VANSHB03_URL),
        ("GET", GREENHOUSE_API),
    ]
    status = client.get("/api/discovery/status").json()
    assert status["scanning"] is False
    assert status["last_scan_at"] is not None
    assert status["last_scan_error"] is None
    assert status["inbox_count"] == len(EXPECTED_INBOX)

    # 3. The Inbox has matching list rows and board rows, and not the
    # Hardware, Summer 2026, Fall, senior, inactive, hidden or javascript: ones.
    items = inbox(client)
    assert {(p["source"], p["company"], p["title"]) for p in items} == EXPECTED_INBOX
    shown = {p["company"] for p in items}
    for left_out in ("IMC Trading", "K1", "Hermeus", "Cisive", "Palantir", "Guidewire", "Geneva Trading",
                     "Royal Caribbean Group", "NBCUniversal", "Notion", "Copart", "Amazon", "Rippling"):
        assert left_out not in shown
    assert not any("Senior" in p["title"] or "Hardware" in p["title"] for p in items)
    assert all(p["url"].startswith("https://") for p in items)
    board_rows = [p for p in items if p["source"] == "greenhouse"]
    assert {p["watch_company_id"] for p in board_rows} == {watch_id}
    [watched] = client.get("/api/discovery/watchlist").json()
    assert watched["open_matches"] == 2
    assert watched["last_checked_at"] is not None and watched["last_error"] is None

    # 4. Save two postings; apply to one of them.
    melius = find(items, "Melius", "Software Engineer Intern")
    tiktok = next(p for p in items if p["company"] == "TikTok")
    for posting in (melius, tiktok):
        r = client.post(f"/api/discovery/postings/{posting['id']}/save")
        assert r.status_code == 200 and r.json()["state"] == "saved"
    saved = client.get("/api/discovery/postings", params={"view": "saved"}).json()
    assert {p["id"] for p in saved["items"]} == {melius["id"], tiktok["id"]}
    assert len(inbox(client)) == len(EXPECTED_INBOX) - 2

    r = client.post(f"/api/discovery/postings/{melius['id']}/apply")
    assert r.status_code == 201
    application = r.json()
    assert application["company"] == "Melius"
    assert application["role_title"] == "Software Engineer Intern"
    assert application["status"] == "applied"
    assert application["date_applied"] == utc_today().isoformat()
    assert application["job_link"] == melius["url"]
    assert application["source"] == "Discover: Simplify"

    [stored_app] = db_session.scalars(select(Application)).all()
    assert stored_app.id == application["id"]
    queue = db_session.scalars(select(ResearchQueueItem)).all()
    assert [(q.kind, q.application_id) for q in queue] == [(QueueKind.COMPANY_CONTACTS, application["id"])]

    # 5. Re-scan with both saved postings marked inactive on the list.
    rescanned = copy.deepcopy(simplify)
    for row in rescanned:
        if row["id"] in (MELIUS_ID, TIKTOK_ID):
            row["active"] = False
    discovery_http.add("GET", SIMPLIFY_URL, json_result(rescanned, url=SIMPLIFY_URL, etag='"s2"'))
    discovery_http.calls.clear()

    assert client.post("/api/discovery/scan").status_code == 202
    simplify_call = next(c for c in discovery_http.calls if c.url == SIMPLIFY_URL)
    assert simplify_call.etag == '"s1"'  # the list is re-downloaded only if it changed
    assert client.get("/api/discovery/status").json()["last_scan_error"] is None

    # The saved one shows closed in Saved; the applied one is closed but kept,
    # still linked to its application. Neither is deleted.
    saved = client.get("/api/discovery/postings", params={"view": "saved"}).json()["items"]
    [still_saved] = saved
    assert still_saved["id"] == tiktok["id"]
    assert still_saved["closed"] is True and still_saved["state"] == "saved"
    applied_row = db_session.get(Posting, melius["id"])
    db_session.refresh(applied_row)
    assert applied_row.closed is True
    assert applied_row.state is PostingState.APPLIED
    assert applied_row.application_id == application["id"]
    assert db_session.get(Application, application["id"]) is not None
    # Untouched rows stay in the Inbox; nothing else was closed.
    assert len(inbox(client)) == len(EXPECTED_INBOX) - 2
    assert len(db_session.scalars(select(ResearchQueueItem)).all()) == 1

    # 6. Paste a careers page with JSON-LD; it lands in Saved.
    page = (FIXTURES / "jobposting_page.html").read_text()
    discovery_http.add("PAGE", PASTED_URL, page_result(page, url=PASTED_URL))
    r = client.post("/api/discovery/paste/preview", json={"url": PASTED_URL})
    assert r.status_code == 200
    preview = r.json()
    assert preview["company"] == "Globex Corporation"
    assert preview["title"] == "Software Engineer Intern, R&D (Summer 2027)"
    assert preview["locations"] == ["Austin, TX, US", "Toronto, ON, Canada"]
    assert preview["source"] == "pasted"
    assert preview["url"] == PASTED_URL

    r = client.post(
        "/api/discovery/paste",
        json={k: preview[k] for k in ("url", "company", "title", "locations", "date_posted")},
    )
    assert r.status_code == 201
    pasted = r.json()
    assert pasted["state"] == "saved" and pasted["source"] == "pasted"

    saved = client.get("/api/discovery/postings", params={"view": "saved"}).json()["items"]
    assert [p["id"] for p in saved] == [pasted["id"], tiktok["id"]]
    assert len(inbox(client)) == len(EXPECTED_INBOX) - 2
    assert db_session.scalars(
        select(Posting).where(Posting.source == PostingSource.PASTED)
    ).one().url == PASTED_URL
