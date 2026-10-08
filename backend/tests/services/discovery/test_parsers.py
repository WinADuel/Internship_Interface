"""Parsers for community lists, job boards and pasted pages (Phase 2 spec §2).

Pure functions over the recorded fixtures in tests/fixtures/discovery/
(see the README there for which fixtures are real data). No network, no DB.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.posting import PostingSource
from app.services.discovery.parsers import (
    MAX_LOCATIONS,
    MAX_TITLE,
    PastedDetails,
    PostingIn,
    clean_text,
    company_from_token,
    find_ashby_job,
    parse_ashby_board,
    parse_greenhouse_board,
    parse_greenhouse_job,
    parse_html_posting,
    parse_lever_board,
    parse_lever_job,
    parse_listings,
    parse_workday_job_detail,
    parse_workday_page,
    parse_workday_posted_on,
    workday_source_key,
)
from app.services.discovery.urls import normalize_url, parse_job_url

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "discovery"

WD_HOST = "acme.wd5.myworkdayjobs.com"
WD_TENANT = "acme"
WD_SITE = "AcmeCareers"
NOW = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def by_key(postings: list[PostingIn]) -> dict[str, PostingIn]:
    return {p.source_key: p for p in postings}


def day(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


# --- clean_text / company_from_token -----------------------------------------


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        ("  Software   Intern \n", 300, "Software Intern"),
        ("a\x00b\x07c\x7fd", 300, "a b c d"),
        ("abcdef", 3, "abc"),
        ("ab   cdef", 4, "ab c"),
        (None, 300, ""),
        (42, 300, ""),
        (["x"], 300, ""),
    ],
)
def test_clean_text(value, limit, expected):
    assert clean_text(value, limit) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("openai", "Openai"), ("acme-robotics", "Acme Robotics"), ("big_co", "Big Co"), ("NVIDIA", "NVIDIA")],
)
def test_company_from_token(token, expected):
    assert company_from_token(token) == expected


# --- parse_listings: Simplify (real trimmed rows) ----------------------------


def test_simplify_listings_counts_and_drops_javascript_url():
    postings = parse_listings(load_json("simplify_listings.json"), PostingSource.SIMPLIFY)
    keys = by_key(postings)
    assert len(postings) == 13  # 14 rows, the injected javascript: row dropped
    assert "injected-javascript-url" not in keys
    assert all(p.url.startswith(("http://", "https://")) for p in postings)
    assert all(p.source is PostingSource.SIMPLIFY for p in postings)
    assert sum(p.active for p in postings) == 10


def test_simplify_listing_fields():
    keys = by_key(parse_listings(load_json("simplify_listings.json"), PostingSource.SIMPLIFY))
    p = keys["15636fe2-413f-4e5d-b6c9-0d42dc5edc5f"]
    assert p == PostingIn(
        source=PostingSource.SIMPLIFY,
        source_key="15636fe2-413f-4e5d-b6c9-0d42dc5edc5f",
        company="Aquatic Capital Management",
        title="Software Engineer Intern",
        locations=["London, UK", "Chicago, IL"],
        url="https://job-boards.greenhouse.io/aquaticcapitalmanagement/jobs/8489233002",
        terms=["Summer 2027"],
        category="Software",
        sponsorship="Other",
        date_posted=datetime.fromtimestamp(1775081547, UTC),
        active=True,
    )


def test_simplify_inactive_and_invisible_rows_are_kept_but_inactive():
    keys = by_key(parse_listings(load_json("simplify_listings.json"), PostingSource.SIMPLIFY))
    assert keys["28f5044f-3ad2-481e-a14e-218db9fa2089"].active is False  # active=false
    assert keys["58821bd1-bd22-45bf-82f0-c375329b1523"].active is False  # is_visible=false
    assert keys["051760ad-4f30-4fcb-b160-bf0e3aa8f9d5"].active is False


def test_simplify_terms_categories_and_sponsorship():
    keys = by_key(parse_listings(load_json("simplify_listings.json"), PostingSource.SIMPLIFY))
    assert keys["56196707-1bc1-44de-9e0e-a32456792771"].terms == ["Spring 2027", "Summer 2027"]
    assert keys["69e6a885-ba62-4040-becf-35815be46d4e"].terms == ["Fall 2026"]
    assert keys["4aa719b5-d2a2-4379-950b-53301335fcac"].category == "Hardware"
    # Older long category names are mapped to the current short ones.
    assert keys["bead841e-a62e-4398-b92e-600ec3c544c4"].category == "AI/ML/Data"
    assert keys["44bbff4b-6183-44c5-93b8-e082f78ee431"].category == "Hardware"
    assert keys["3350268b-7da8-41ee-bcc6-c85f795975ac"].category == "Software"
    assert {p.sponsorship for p in keys.values()} == {
        "Other",
        "Does Not Offer Sponsorship",
        "U.S. Citizenship is Required",
        "Offers Sponsorship",
    }


def test_simplify_caps_locations_and_title_and_collapses_whitespace():
    keys = by_key(parse_listings(load_json("simplify_listings.json"), PostingSource.SIMPLIFY))
    cisive = keys["e018a2ac-82d3-4544-85aa-440aa29efa03"]
    assert len(cisive.locations) == MAX_LOCATIONS == 20
    big = keys["injected-50kb-title"]
    assert len(big.title) == MAX_TITLE == 300
    assert big.title.startswith("Software Engineer Intern AAAA")
    assert keys["051760ad-4f30-4fcb-b160-bf0e3aa8f9d5"].title == "SACC Intern Developer Intern"


# --- parse_listings: vanshb03 (real trimmed rows) ----------------------------


def test_vanshb03_listings():
    postings = parse_listings(load_json("vanshb03_listings.json"), PostingSource.VANSHB03)
    keys = by_key(postings)
    assert len(postings) == 10
    assert "injected-javascript-url" not in keys
    assert len(keys["injected-50kb-title"].title) == 300
    assert sum(not p.active for p in postings) == 1
    assert keys["cfb9420c-289e-4b59-822d-a687edbdac21"].active is False
    point72 = keys["2d295ad5-b2e7-4771-98ad-e40ef675596e"]
    assert point72.source is PostingSource.VANSHB03
    assert point72.company == "Point72"
    assert point72.terms == ["Summer"]  # `season` is a bare season word
    assert point72.category is None
    assert point72.locations[:2] == ["New York, NY", "San Francisco, CA"]
    assert point72.date_posted == datetime.fromtimestamp(1776617707, UTC)
    assert keys["f1fb259b-d4f0-4533-bff6-ab51a408a4db"].terms == ["Spring", "Summer"]
    assert keys["0a293944-e823-414b-8259-4f2086dc41ac"].terms == []  # season "null"
    assert len(keys["5523431f-7de5-4e00-be54-8f529bcf2e50"].locations) == 20


# --- parse_listings: hostile and malformed input -----------------------------


def _row(**overrides):
    row = {
        "id": "row-1",
        "company_name": "Acme",
        "title": "Software Intern",
        "locations": ["Remote"],
        "url": "https://example.com/jobs/1",
        "active": True,
        "is_visible": True,
        "date_posted": 1790000000,
        "terms": ["Summer 2027"],
        "category": "Software",
        "sponsorship": "Other",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("data", [None, {}, {"rows": []}, "[]", 42])
def test_listings_non_list_input_is_empty(data):
    assert parse_listings(data, PostingSource.SIMPLIFY) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "javascript:alert(1)"},
        {"url": "ftp://example.com/x"},
        {"url": "/relative/path"},
        {"url": "https://example.com/" + "a" * 2000},
        {"url": None},
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"company_name": ""},
        {"company_name": {"name": "Acme"}},
    ],
)
def test_listing_rows_without_safe_url_title_or_company_are_dropped(overrides):
    assert parse_listings([_row(**overrides)], PostingSource.SIMPLIFY) == []


def test_listing_skips_non_object_rows():
    postings = parse_listings(["x", None, 3, [], _row()], PostingSource.SIMPLIFY)
    assert [p.source_key for p in postings] == ["row-1"]


def test_listing_field_caps_and_defensive_types():
    row = _row(
        company_name="C" * 1000,
        locations=["L" * 500, "", None, 7, "Remote", "Remote"],
        terms="Summer 2027",
        category=["x"],
        sponsorship=None,
        date_posted="yesterday",
        id=12345,
    )
    (p,) = parse_listings([row], PostingSource.LIST)
    assert len(p.company) == 300
    assert p.locations == ["L" * 200, "Remote"]
    assert p.terms == ["Summer 2027"]
    assert p.category is None
    assert p.sponsorship is None
    assert p.date_posted is None
    assert p.source_key == "12345"


@pytest.mark.parametrize("value", [True, -5, 10**12, float("nan"), "1790000000"])
def test_listing_bad_date_posted_is_none(value):
    (p,) = parse_listings([_row(date_posted=value)], PostingSource.SIMPLIFY)
    assert p.date_posted is None


def test_listing_without_id_falls_back_to_url_key():
    url = "https://Example.com/jobs/1?utm_source=x"
    (p,) = parse_listings([_row(id=None, url=url)], PostingSource.SIMPLIFY)
    assert p.source_key == normalize_url(url) == "https://example.com/jobs/1"
    assert p.url == url


def test_listing_active_flags():
    rows = [
        _row(id="a", active=True, is_visible=True),
        _row(id="b", active=False),
        _row(id="c", is_visible=False),
        _row(id="d"),
    ]
    del rows[3]["is_visible"]
    keys = by_key(parse_listings(rows, PostingSource.SIMPLIFY))
    assert [keys[k].active for k in "abcd"] == [True, False, False, True]


def test_listing_strips_control_characters():
    (p,) = parse_listings([_row(title="Intern\x00\u0007 Role", company_name="Ac\nme")], PostingSource.SIMPLIFY)
    assert p.title == "Intern Role"
    assert p.company == "Ac me"


# --- Greenhouse --------------------------------------------------------------


def test_greenhouse_board():
    postings = parse_greenhouse_board(load_json("greenhouse_board.json"), "acmerobotics", "Acme")
    keys = by_key(postings)
    # 5 jobs: one javascript: URL and one empty title are dropped.
    assert set(keys) == {"4012345001", "4012345002", "4012345003"}
    p = keys["4012345001"]
    assert p == PostingIn(
        source=PostingSource.GREENHOUSE,
        source_key="4012345001",
        company="Acme",
        title="Software Engineering Intern, Summer 2027",
        locations=["San Francisco, CA"],
        url="https://job-boards.greenhouse.io/acmerobotics/jobs/4012345001?gh_src=abc123",
        terms=[],
        category=None,
        sponsorship=None,
        date_posted=datetime(2026, 9, 28, 13, 30, tzinfo=UTC),
        active=True,
    )
    # first_published null -> updated_at
    assert keys["4012345002"].date_posted == datetime(2026, 10, 3, 8, 15, tzinfo=UTC)
    assert keys["4012345003"].locations == []
    assert keys["4012345003"].title == "Machine Learning Intern"


@pytest.mark.parametrize("data", [None, [], {"jobs": None}, {"jobs": "x"}, {"jobs": [None, 1]}])
def test_greenhouse_board_malformed(data):
    assert parse_greenhouse_board(data, "acme", "Acme") == []


def test_greenhouse_job():
    details = parse_greenhouse_job(load_json("greenhouse_job.json"), "acmerobotics")
    assert details == PastedDetails(
        company="Acme Robotics",
        title="Software Engineering Intern, Summer 2027",
        locations=["San Francisco, CA"],
        date_posted=datetime(2026, 9, 28, 13, 30, tzinfo=UTC),
        source=PostingSource.GREENHOUSE,
        source_key="4012345001",
    )


def test_greenhouse_job_company_falls_back_to_token_and_bad_input_is_none():
    data = load_json("greenhouse_job.json")
    del data["company_name"]
    assert parse_greenhouse_job(data, "acme-robotics").company == "Acme Robotics"
    assert parse_greenhouse_job({"id": 1}, "acme") is None
    assert parse_greenhouse_job([], "acme") is None


# --- Lever -------------------------------------------------------------------


def test_lever_board():
    postings = parse_lever_board(load_json("lever_board.json"), "acmerobotics", "Acme")
    keys = by_key(postings)
    assert set(keys) == {
        "5ac21346-8e0c-4494-8e7a-3eb92ff77902",
        "0f8d2c4e-1b3a-4c5d-9e7f-123456789abc",
        "9b1e7a52-6c3d-4f8e-a0b1-c2d3e4f5a6b7",
    }  # the javascript: hostedUrl row is dropped
    coop = keys["5ac21346-8e0c-4494-8e7a-3eb92ff77902"]
    assert coop.source is PostingSource.LEVER
    assert coop.title == "Software Developer Co-op (Winter 2027)"
    assert coop.company == "Acme"
    assert coop.locations == ["Toronto, ON", "Waterloo, ON"]
    assert coop.url == "https://jobs.lever.co/acmerobotics/5ac21346-8e0c-4494-8e7a-3eb92ff77902"
    assert coop.date_posted == datetime.fromtimestamp(1790000000, UTC)
    assert coop.active is True and coop.terms == []
    assert keys["0f8d2c4e-1b3a-4c5d-9e7f-123456789abc"].locations == ["New York, NY"]
    assert keys["9b1e7a52-6c3d-4f8e-a0b1-c2d3e4f5a6b7"].locations == []


@pytest.mark.parametrize("data", [None, {"ok": False, "error": "Document not found"}, "x", [1, None]])
def test_lever_board_malformed(data):
    assert parse_lever_board(data, "acme", "Acme") == []


def test_lever_job():
    details = parse_lever_job(load_json("lever_job.json"), "acme-robotics")
    assert details == PastedDetails(
        company="Acme Robotics",
        title="Software Developer Co-op (Winter 2027)",
        locations=["Toronto, ON", "Waterloo, ON"],
        date_posted=datetime.fromtimestamp(1790000000, UTC),
        source=PostingSource.LEVER,
        source_key="5ac21346-8e0c-4494-8e7a-3eb92ff77902",
    )
    assert parse_lever_job({"ok": False}, "acme") is None


# --- Ashby -------------------------------------------------------------------


def test_ashby_board_skips_unlisted():
    postings = parse_ashby_board(load_json("ashby_board.json"), "acmerobotics", "Acme")
    keys = by_key(postings)
    assert set(keys) == {
        "2bb6be67-d1a8-42f7-bb1b-64ee36bf613f",
        "e4f5a6b7-c8d9-4e0f-a1b2-c3d4e5f6a7b8",
    }
    p = keys["2bb6be67-d1a8-42f7-bb1b-64ee36bf613f"]
    assert p.source is PostingSource.ASHBY
    assert p.title == "Research Engineer Intern"
    assert p.locations == ["San Francisco", "New York", "Remote (US)"]
    assert p.url == "https://jobs.ashbyhq.com/acmerobotics/2bb6be67-d1a8-42f7-bb1b-64ee36bf613f"
    assert p.date_posted == datetime(2026, 9, 30, 17, 2, 11, 123000, tzinfo=UTC)
    assert keys["e4f5a6b7-c8d9-4e0f-a1b2-c3d4e5f6a7b8"].locations == ["Remote"]


@pytest.mark.parametrize("data", [None, [], {"jobs": {}}, {"jobs": [None]}])
def test_ashby_board_malformed(data):
    assert parse_ashby_board(data, "acme", "Acme") == []


def test_find_ashby_job():
    board = load_json("ashby_board.json")
    details = find_ashby_job(board, "2BB6BE67-D1A8-42F7-BB1B-64EE36BF613F", "acme-robotics")
    assert details == PastedDetails(
        company="Acme Robotics",
        title="Research Engineer Intern",
        locations=["San Francisco", "New York", "Remote (US)"],
        date_posted=datetime(2026, 9, 30, 17, 2, 11, 123000, tzinfo=UTC),
        source=PostingSource.ASHBY,
        source_key="2bb6be67-d1a8-42f7-bb1b-64ee36bf613f",
    )
    assert find_ashby_job(board, "00000000-0000-0000-0000-000000000000", "acme") is None
    # An unlisted job is still found when the user pastes its direct link.
    assert find_ashby_job(board, "7c9d0e1f-2a3b-4c5d-8e9f-0a1b2c3d4e5f", "acme") is not None
    assert find_ashby_job(None, "x", "acme") is None


# --- Workday -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Posted Today", day(2026, 10, 8)),
        ("Posted Yesterday", day(2026, 10, 7)),
        ("Posted 1 Day Ago", day(2026, 10, 7)),
        ("Posted 3 Days Ago", day(2026, 10, 5)),
        ("Posted 30+ Days Ago", day(2026, 9, 8)),
        ("posted 12 days ago", day(2026, 9, 26)),
        ("Posted 999 Days Ago", None),
        ("Posted Last Week", None),
        ("", None),
        (None, None),
        (5, None),
    ],
)
def test_parse_workday_posted_on(text, expected):
    assert parse_workday_posted_on(text, NOW) == expected


def test_workday_page1():
    postings, total = parse_workday_page(
        load_json("workday_jobs_page1.json"), WD_HOST, WD_TENANT, WD_SITE, "Acme", now=NOW
    )
    assert total == 23
    assert len(postings) == 19  # 20 entries, the javascript: externalPath dropped
    first = postings[0]
    path = "/job/US-CA-Santa-Clara/Software-Engineering-Intern---Summer-2027_JR2001001"
    assert first == PostingIn(
        source=PostingSource.WORKDAY,
        source_key=f"{WD_HOST}/{WD_TENANT}/{WD_SITE}{path}",
        company="Acme",
        title="Software Engineering Intern - Summer 2027",
        locations=["US, CA, Santa Clara"],
        url=f"https://{WD_HOST}/{WD_SITE}{path}",
        terms=[],
        category=None,
        sponsorship=None,
        date_posted=day(2026, 10, 8),
        active=True,
    )
    by_title = {p.title: p for p in postings}
    assert by_title["Hardware Design Intern - Summer 2027"].locations == []  # "2 Locations"
    assert by_title["Hardware Design Intern - Summer 2027"].date_posted == day(2026, 10, 7)
    assert by_title["Deep Learning Intern"].date_posted == day(2026, 10, 5)
    assert by_title["Systems Software Intern"].date_posted == day(2026, 9, 8)
    assert by_title["Verification Intern"].date_posted is None
    assert "Firmware Intern" not in by_title


def test_workday_page2_total_zero():
    postings, total = parse_workday_page(
        load_json("workday_jobs_page2.json"), WD_HOST, WD_TENANT, WD_SITE, "Acme", now=NOW
    )
    assert total == 0
    assert len(postings) == 3


@pytest.mark.parametrize(
    "path",
    [
        "javascript:alert(1)",
        "https://evil.example/job/x",
        "//evil.example/job/x",
        "/job/../../wday/x",
        "/job/a b",
        "/job/x?y=1",
        "job/no-leading-slash",
        "",
        None,
    ],
)
def test_workday_unsafe_external_path_dropped(path):
    data = {"total": 1, "jobPostings": [{"title": "Intern", "externalPath": path}]}
    postings, total = parse_workday_page(data, WD_HOST, WD_TENANT, WD_SITE, "Acme", now=NOW)
    assert postings == [] and total == 1


@pytest.mark.parametrize("data", [None, [], {"total": "x", "jobPostings": None}, {"jobPostings": [3]}])
def test_workday_page_malformed(data):
    assert parse_workday_page(data, WD_HOST, WD_TENANT, WD_SITE, "Acme", now=NOW) == ([], 0)


def test_workday_job_detail_matches_board_key_and_paste_ref():
    url = (
        f"https://{WD_HOST}/en-US/{WD_SITE}/job/US-CA-Santa-Clara/"
        "Software-Engineering-Intern---Summer-2027_JR2001001"
    )
    ref = parse_job_url(url)
    assert ref is not None
    details = parse_workday_job_detail(
        load_json("workday_job_detail.json"), WD_HOST, WD_TENANT, WD_SITE, ref.job_id, now=NOW
    )
    assert details == PastedDetails(
        company="Acme Robotics",
        title="Software Engineering Intern - Summer 2027",
        locations=["US, CA, Santa Clara", "US, TX, Austin", "US, WA, Seattle"],
        date_posted=day(2026, 10, 1),
        source=PostingSource.WORKDAY,
        source_key=workday_source_key(
            WD_HOST, WD_TENANT, WD_SITE,
            "/job/US-CA-Santa-Clara/Software-Engineering-Intern---Summer-2027_JR2001001",
        ),
    )
    board, _ = parse_workday_page(
        load_json("workday_jobs_page1.json"), WD_HOST, WD_TENANT, WD_SITE, "Acme", now=NOW
    )
    assert details.source_key == board[0].source_key


def test_workday_job_detail_fallbacks():
    data = load_json("workday_job_detail.json")
    del data["hiringOrganization"]
    del data["jobPostingInfo"]["startDate"]
    details = parse_workday_job_detail(data, WD_HOST, WD_TENANT, WD_SITE, "job/x/y_1", now=NOW)
    assert details.company == "Acme"  # the tenant, prettified
    assert details.date_posted == day(2026, 10, 5)  # from postedOn
    assert parse_workday_job_detail({}, WD_HOST, WD_TENANT, WD_SITE, "job/x", now=NOW) is None


# --- Pasted pages ------------------------------------------------------------


def test_html_jobposting_in_graph_after_malformed_and_other_scripts():
    url = "https://careers.globex.example/jobs/42?utm_source=x"
    details = parse_html_posting(load_text("jobposting_page.html"), url)
    assert details == PastedDetails(
        company="Globex Corporation",
        title="Software Engineer Intern, R&D (Summer 2027)",
        locations=["Austin, TX, US", "Toronto, ON, Canada"],
        date_posted=day(2026, 9, 30),
        source=PostingSource.PASTED,
        source_key="https://careers.globex.example/jobs/42",
    )


def test_html_title_only_fallback():
    details = parse_html_posting(
        load_text("title_only_page.html"), "https://jobs.acme-robotics.co.uk/openings/7"
    )
    assert details.title == "Embedded Systems Intern – Summer 2027"
    assert details.company == "Acme Robotics"  # registrable host label
    assert details.locations == []
    assert details.date_posted is None
    assert details.source is PostingSource.PASTED
    assert details.source_key == "https://jobs.acme-robotics.co.uk/openings/7"


def _page(head: str, body: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


def _ld(obj) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


def test_html_jsonld_plain_object_list_and_remote():
    posting = {
        "@type": "JobPosting",
        "title": "Data Intern",
        "hiringOrganization": "Initech",
        "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "TX"}},
        "jobLocationType": "TELECOMMUTE",
        "datePosted": "2026-09-01T10:00:00-05:00",
    }
    for payload in (posting, [{"@type": "Organization"}, posting]):
        details = parse_html_posting(_page(_ld(payload)), "https://initech.example/j/1")
        assert details.title == "Data Intern"
        assert details.company == "Initech"
        assert details.locations == ["Austin, TX", "Remote"]
        assert details.date_posted == datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def test_html_og_title_and_site_name_fallbacks():
    head = (
        '<meta property="og:title" content="QA Intern">'
        '<meta property="og:site_name" content="Hooli Careers">'
        "<title>Ignored</title>"
    )
    details = parse_html_posting(_page(head), "https://www.hooli.example/jobs/9")
    assert details.title == "QA Intern"
    assert details.company == "Hooli Careers"


def test_html_jobposting_without_company_uses_og_site_name_then_host():
    ld = _ld({"@type": "JobPosting", "title": "Ops Intern"})
    with_site = _page(ld + '<meta property="og:site_name" content="Vandelay">')
    assert parse_html_posting(with_site, "https://x.example/j").company == "Vandelay"
    assert parse_html_posting(_page(ld), "https://www.vandelay-industries.com/j").company == (
        "Vandelay Industries"
    )


def test_html_nothing_usable():
    details = parse_html_posting("<html><body>No title here</body></html>", "https://a.example/j")
    assert details.title == ""
    assert details.company == "A"
    assert details.locations == []


def test_html_caps_and_cleans_untrusted_fields():
    posting = {
        "@type": "JobPosting",
        "title": "T" * 5000,
        "hiringOrganization": {"name": "N\x00ame"},
        "jobLocation": [{"address": {"addressLocality": f"City {i}"}} for i in range(50)],
        "datePosted": "not a date",
    }
    details = parse_html_posting(_page(_ld(posting)), "https://a.example/j")
    assert len(details.title) == 300
    assert details.company == "N ame"
    assert len(details.locations) == 20
    assert details.date_posted is None


def test_html_deeply_nested_jsonld_does_not_crash():
    nested = "[" * 5000 + "]" * 5000
    html = _page(f'<script type="application/ld+json">{nested}</script><title>Fallback</title>')
    assert parse_html_posting(html, "https://a.example/j").title == "Fallback"


def test_html_ignores_non_jsonld_scripts():
    script = '<script>{"@type": "JobPosting", "title": "Executable"}</script>'
    html = _page(script + "<title>Real</title>")
    assert parse_html_posting(html, "https://a.example/j").title == "Real"


def test_lever_and_ashby_uuid_keys_are_lowercased_like_parse_job_url():
    lever = load_json("lever_board.json")
    lever[0]["id"] = lever[0]["id"].upper()
    assert parse_lever_board(lever, "acme", "Acme")[0].source_key == (
        "5ac21346-8e0c-4494-8e7a-3eb92ff77902"
    )
    ashby = load_json("ashby_board.json")
    ashby["jobs"][0]["id"] = ashby["jobs"][0]["id"].upper()
    assert parse_ashby_board(ashby, "acme", "Acme")[0].source_key == (
        "2bb6be67-d1a8-42f7-bb1b-64ee36bf613f"
    )
