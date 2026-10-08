"""List, board and pasted-link fetchers (Phase 2 spec §2, plan Task 4).

Every request goes through `FakeDiscoveryHttp`; no test touches the network.
Each test also checks the exact URLs requested, so nothing is ever fetched
from a URL that was not built from a validated token.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.app_settings import DEFAULT_LIST_URLS
from app.models.posting import PostingSource
from app.models.watch_company import WatchAts, WatchCompany
from app.services.discovery.http import (
    DEFAULT_TIMEOUT,
    LIST_MAX_BYTES,
    LIST_TIMEOUT,
    PAGE_MAX_BYTES,
    DiscoveryFetchError,
    FetchResult,
)
from app.services.discovery.parsers import MAX_SOURCE_KEY
from app.services.discovery.sources import (
    LIST_SOURCE_BY_URL,
    WORKDAY_MAX_PER_KEYWORD,
    WORKDAY_PAGE_SIZE,
    SourceResult,
    fetch_board,
    fetch_list,
    fetch_pasted,
    list_key_prefix,
    list_source,
)
from tests.services.discovery.fakes import (
    FakeCall,
    FakeDiscoveryHttp,
    json_result,
    page_result,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "discovery"
NOW = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)

SIMPLIFY_URL, VANSHB03_URL = DEFAULT_LIST_URLS
CUSTOM_URL = "https://raw.githubusercontent.com/someone/Fall2027-Internships/dev/.github/scripts/listings.json"
OTHER_CUSTOM_URL = (
    "https://raw.githubusercontent.com/other/Fall2027-Internships/dev/listings.json"
)

GH_BOARD_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
LEVER_BOARD_API = "https://api.lever.co/v0/postings/acme?mode=json"
ASHBY_BOARD_API = (
    "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=false"
)
WD_HOST = "nvidia.wd5.myworkdayjobs.com"
WD_SITE = "NVIDIAExternalCareerSite"
WD_TOKEN = f"{WD_HOST}/nvidia/{WD_SITE}"
WD_JOBS_API = f"https://{WD_HOST}/wday/cxs/nvidia/{WD_SITE}/jobs"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def company(
    ats: WatchAts, token: str = "acme", name: str = "Acme Robotics"
) -> WatchCompany:
    return WatchCompany(
        id=7, name=name, ats=ats, board_token=token, careers_url="https://x.test/"
    )


def not_modified(etag: str | None = '"abc"') -> FetchResult:
    return FetchResult(
        status=304, data=None, text=None, etag=etag, final_url=SIMPLIFY_URL
    )


def urls(http: FakeDiscoveryHttp) -> list[tuple[str, str]]:
    return [(c.method, c.url) for c in http.calls]


def assert_failed(result: SourceResult, name: str, fragment: str) -> None:
    assert result.postings == []
    assert result.complete is False
    assert result.not_modified is False
    assert result.error is not None
    assert result.error.startswith(f"{name}: ")
    assert fragment in result.error
    assert "\n" not in result.error


# --- list sources ------------------------------------------------------------


def test_list_source_by_url_maps_the_two_known_lists():
    assert LIST_SOURCE_BY_URL == {
        SIMPLIFY_URL: PostingSource.SIMPLIFY,
        VANSHB03_URL: PostingSource.VANSHB03,
    }
    assert list_source(SIMPLIFY_URL) is PostingSource.SIMPLIFY
    assert list_source(VANSHB03_URL) is PostingSource.VANSHB03
    assert list_source(CUSTOM_URL) is PostingSource.LIST


def test_list_key_prefix_is_short_stable_and_distinct():
    prefix = list_key_prefix(CUSTOM_URL)
    assert prefix == list_key_prefix(CUSTOM_URL)
    assert prefix != list_key_prefix(OTHER_CUSTOM_URL)
    assert 6 <= len(prefix) <= 16
    assert prefix.isalnum()


# --- fetch_list --------------------------------------------------------------


def test_fetch_list_simplify_returns_complete_result_with_etag():
    data = load_json("simplify_listings.json")
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result(data, etag='"v2"')})

    result = fetch_list(http, SIMPLIFY_URL, '"v1"')

    assert result.error is None
    assert result.complete is True
    assert result.not_modified is False
    assert result.etag == '"v2"'
    assert result.key_prefix is None
    assert len(result.postings) == 13
    assert {p.source for p in result.postings} == {PostingSource.SIMPLIFY}
    assert result.postings[0].source_key == "15636fe2-413f-4e5d-b6c9-0d42dc5edc5f"
    assert http.calls == [
        FakeCall(
            "GET",
            SIMPLIFY_URL,
            etag='"v1"',
            max_bytes=LIST_MAX_BYTES,
            timeout=LIST_TIMEOUT,
        )
    ]


def test_fetch_list_vanshb03_uses_its_source():
    http = FakeDiscoveryHttp(
        {("GET", VANSHB03_URL): json_result(load_json("vanshb03_listings.json"))}
    )
    result = fetch_list(http, VANSHB03_URL, None)
    assert result.complete is True
    assert {p.source for p in result.postings} == {PostingSource.VANSHB03}
    assert http.calls[0].etag is None


def test_fetch_list_custom_url_prefixes_keys_so_two_lists_never_collide():
    data = load_json("vanshb03_listings.json")
    http = FakeDiscoveryHttp(
        {
            ("GET", CUSTOM_URL): json_result(data),
            ("GET", OTHER_CUSTOM_URL): json_result(data),
        }
    )
    first = fetch_list(http, CUSTOM_URL, None)
    second = fetch_list(http, OTHER_CUSTOM_URL, None)

    assert {p.source for p in first.postings + second.postings} == {PostingSource.LIST}
    assert first.key_prefix == list_key_prefix(CUSTOM_URL)
    assert second.key_prefix == list_key_prefix(OTHER_CUSTOM_URL)
    assert all(p.source_key.startswith(first.key_prefix + ":") for p in first.postings)
    assert all(
        p.source_key.startswith(second.key_prefix + ":") for p in second.postings
    )
    assert not {p.source_key for p in first.postings} & {
        p.source_key for p in second.postings
    }


def test_fetch_list_custom_url_drops_keys_too_long_after_prefixing():
    row = {
        "id": "k" * MAX_SOURCE_KEY,
        "company_name": "Acme",
        "title": "Intern",
        "url": "https://acme.test/jobs/1",
        "locations": [],
    }
    ok = dict(row, id="short", url="https://acme.test/jobs/2")
    http = FakeDiscoveryHttp({("GET", CUSTOM_URL): json_result([row, ok])})
    result = fetch_list(http, CUSTOM_URL, None)
    assert [p.source_key for p in result.postings] == [
        f"{list_key_prefix(CUSTOM_URL)}:short"
    ]
    assert all(len(p.source_key) <= MAX_SOURCE_KEY for p in result.postings)


def test_fetch_list_304_is_not_modified_and_not_complete():
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): not_modified('"v1"')})
    result = fetch_list(http, SIMPLIFY_URL, '"v1"')
    assert result.not_modified is True
    assert result.complete is False
    assert result.postings == []
    assert result.error is None
    assert result.etag == '"v1"'


def test_fetch_list_304_without_etag_header_keeps_the_sent_etag():
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): not_modified(None)})
    result = fetch_list(http, SIMPLIFY_URL, '"v1"')
    assert result.not_modified is True
    assert result.etag == '"v1"'


def test_fetch_list_server_error_is_recorded_not_raised():
    http = FakeDiscoveryHttp(
        {
            ("GET", SIMPLIFY_URL): DiscoveryFetchError(
                "raw.githubusercontent.com/x: status 500", status=500
            )
        }
    )
    result = fetch_list(http, SIMPLIFY_URL, '"v1"')
    assert_failed(result, result.name, "status 500")
    assert result.etag is None


def test_fetch_list_timeout_is_recorded():
    http = FakeDiscoveryHttp(
        {
            ("GET", VANSHB03_URL): DiscoveryFetchError(
                "raw.githubusercontent.com/x: timed out"
            )
        }
    )
    result = fetch_list(http, VANSHB03_URL, None)
    assert_failed(result, result.name, "timed out")


def test_fetch_list_invalid_json_is_recorded():
    http = FakeDiscoveryHttp(
        {
            ("GET", SIMPLIFY_URL): DiscoveryFetchError(
                "raw.githubusercontent.com/x: invalid json"
            )
        }
    )
    assert_failed(fetch_list(http, SIMPLIFY_URL, None), "Simplify list", "invalid json")


@pytest.mark.parametrize("data", [{"listings": []}, "oops", None, 42])
def test_fetch_list_wrong_shape_fails_instead_of_closing_everything(data):
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result(data)})
    assert_failed(
        fetch_list(http, SIMPLIFY_URL, None), "Simplify list", "unexpected response"
    )


def test_fetch_list_rows_with_no_usable_posting_fail_instead_of_closing_everything():
    http = FakeDiscoveryHttp(
        {("GET", SIMPLIFY_URL): json_result([{"foo": 1}, {"bar": 2}])}
    )
    assert_failed(
        fetch_list(http, SIMPLIFY_URL, None), "Simplify list", "unexpected response"
    )


def test_fetch_list_empty_list_is_a_complete_empty_result():
    http = FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([])})
    result = fetch_list(http, SIMPLIFY_URL, None)
    assert result.error is None
    assert result.complete is True
    assert result.postings == []


def test_fetch_list_names():
    assert (
        fetch_list(
            FakeDiscoveryHttp({("GET", SIMPLIFY_URL): json_result([])}),
            SIMPLIFY_URL,
            None,
        ).name
        == "Simplify list"
    )
    assert (
        fetch_list(
            FakeDiscoveryHttp({("GET", VANSHB03_URL): json_result([])}),
            VANSHB03_URL,
            None,
        ).name
        == "vanshb03 list"
    )
    custom = fetch_list(
        FakeDiscoveryHttp({("GET", CUSTOM_URL): json_result([])}), CUSTOM_URL, None
    )
    assert custom.name.startswith("List raw.githubusercontent.com/someone/")
    assert "\n" not in custom.name and len(custom.name) <= 200


# --- fetch_board: Greenhouse, Lever, Ashby -----------------------------------


@pytest.mark.parametrize(
    ("ats", "api_url", "fixture", "source", "count"),
    [
        (
            WatchAts.GREENHOUSE,
            GH_BOARD_API,
            "greenhouse_board.json",
            PostingSource.GREENHOUSE,
            3,
        ),
        (WatchAts.LEVER, LEVER_BOARD_API, "lever_board.json", PostingSource.LEVER, 3),
        (WatchAts.ASHBY, ASHBY_BOARD_API, "ashby_board.json", PostingSource.ASHBY, 2),
    ],
)
def test_fetch_board_reads_one_api_url(ats, api_url, fixture, source, count):
    http = FakeDiscoveryHttp({("GET", api_url): json_result(load_json(fixture))})

    result = fetch_board(http, company(ats), ["intern"])

    assert result.error is None
    assert result.complete is True
    assert result.name == "Acme Robotics"
    assert len(result.postings) == count
    assert {p.source for p in result.postings} == {source}
    assert {p.company for p in result.postings} == {"Acme Robotics"}
    assert http.calls == [
        FakeCall(
            "GET", api_url, etag=None, max_bytes=LIST_MAX_BYTES, timeout=DEFAULT_TIMEOUT
        )
    ]


@pytest.mark.parametrize(
    ("ats", "api_url"),
    [
        (WatchAts.GREENHOUSE, GH_BOARD_API),
        (WatchAts.LEVER, LEVER_BOARD_API),
        (WatchAts.ASHBY, ASHBY_BOARD_API),
    ],
)
@pytest.mark.parametrize(
    ("response", "fragment"),
    [
        (DiscoveryFetchError("api.test/x: status 500", status=500), "status 500"),
        (DiscoveryFetchError("api.test/x: timed out"), "timed out"),
        (DiscoveryFetchError("api.test/x: invalid json"), "invalid json"),
    ],
)
def test_fetch_board_failure_is_recorded(ats, api_url, response, fragment):
    http = FakeDiscoveryHttp({("GET", api_url): response})
    assert_failed(fetch_board(http, company(ats), []), "Acme Robotics", fragment)


@pytest.mark.parametrize(
    ("ats", "api_url", "data"),
    [
        (WatchAts.GREENHOUSE, GH_BOARD_API, []),
        (WatchAts.GREENHOUSE, GH_BOARD_API, {"jobs": "nope"}),
        (WatchAts.GREENHOUSE, GH_BOARD_API, {"jobs": [{"foo": 1}]}),
        (WatchAts.LEVER, LEVER_BOARD_API, {"jobs": []}),
        (WatchAts.LEVER, LEVER_BOARD_API, [{"foo": 1}]),
        (WatchAts.ASHBY, ASHBY_BOARD_API, {"no_jobs": []}),
        (WatchAts.ASHBY, ASHBY_BOARD_API, [1, 2]),
    ],
)
def test_fetch_board_malformed_payload_fails_instead_of_closing_everything(
    ats, api_url, data
):
    http = FakeDiscoveryHttp({("GET", api_url): json_result(data)})
    assert_failed(
        fetch_board(http, company(ats), []), "Acme Robotics", "unexpected response"
    )


@pytest.mark.parametrize(
    ("ats", "api_url", "data"),
    [
        (WatchAts.GREENHOUSE, GH_BOARD_API, {"jobs": [], "meta": {"total": 0}}),
        (WatchAts.LEVER, LEVER_BOARD_API, []),
        (WatchAts.ASHBY, ASHBY_BOARD_API, {"jobs": []}),
    ],
)
def test_fetch_board_empty_board_is_complete(ats, api_url, data):
    http = FakeDiscoveryHttp({("GET", api_url): json_result(data)})
    result = fetch_board(http, company(ats), [])
    assert result.error is None
    assert result.complete is True
    assert result.postings == []


def test_fetch_board_ashby_with_only_unlisted_jobs_is_complete_and_empty():
    data = {
        "jobs": [
            {
                "id": "x",
                "title": "Intern",
                "isListed": False,
                "jobUrl": "https://a.test/1",
            }
        ]
    }
    http = FakeDiscoveryHttp({("GET", ASHBY_BOARD_API): json_result(data)})
    result = fetch_board(http, company(WatchAts.ASHBY), [])
    assert result.error is None
    assert result.complete is True
    assert result.postings == []


@pytest.mark.parametrize(
    ("ats", "token"),
    [
        (WatchAts.GREENHOUSE, "acme/../../evil"),
        (WatchAts.GREENHOUSE, "evil.com"),
        (WatchAts.LEVER, "acme?mode=json&x=1"),
        (WatchAts.ASHBY, "acme#frag"),
        (WatchAts.ASHBY, ""),
        (WatchAts.GREENHOUSE, "a" * 101),
        (WatchAts.WORKDAY, "evil.com/nvidia/site"),
        (WatchAts.WORKDAY, f"{WD_HOST}/other/{WD_SITE}"),  # tenant must match the host
        (WatchAts.WORKDAY, f"{WD_HOST}/nvidia"),
        (WatchAts.WORKDAY, f"{WD_HOST}/nvidia/{WD_SITE}/extra"),
        (WatchAts.WORKDAY, f"{WD_HOST}/nvidia/../x"),
        (WatchAts.WORKDAY, "nvidia.wd5.myworkdayjobs.com.evil.com/nvidia/site"),
    ],
)
def test_fetch_board_refuses_a_malformed_token_without_any_request(ats, token):
    http = FakeDiscoveryHttp()
    result = fetch_board(http, company(ats, token=token), ["intern"])
    assert_failed(result, "Acme Robotics", "invalid board")
    assert http.calls == []


def test_fetch_board_name_is_one_line_and_capped():
    http = FakeDiscoveryHttp()
    result = fetch_board(
        http,
        company(WatchAts.GREENHOUSE, token="bad/token", name="Evil\nCo" + "x" * 500),
        [],
    )
    assert "\n" not in result.name and len(result.name) <= 200
    assert "\n" not in result.error


# --- fetch_board: Workday ----------------------------------------------------


def workday_responder(pages: dict[str, list], totals: dict[str, int]):
    """Answer Workday search POSTs: pages[keyword][offset // 20] -> jobPostings rows."""

    def respond(call: FakeCall) -> FetchResult:
        keyword = call.body["searchText"]
        index = call.body["offset"] // WORKDAY_PAGE_SIZE
        rows = pages.get(keyword, [])
        page = rows[index] if index < len(rows) else []
        total = totals.get(keyword, 0) if index == 0 else 0  # later pages report 0
        return json_result({"total": total, "jobPostings": page})

    return respond


def wd_row(n: int, title: str | None = None) -> dict:
    return {
        "title": title or f"Engineering Intern {n}",
        "externalPath": f"/job/US-CA-Santa-Clara/Engineering-Intern_JR{n:07d}",
        "locationsText": "US, CA, Santa Clara",
        "postedOn": "Posted Today",
    }


def test_fetch_board_workday_pages_with_total_from_the_first_page():
    page1, page2 = (
        load_json("workday_jobs_page1.json"),
        load_json("workday_jobs_page2.json"),
    )
    assert page1["total"] == 23 and page2["total"] == 0
    http = FakeDiscoveryHttp(
        {("POST", WD_JOBS_API): [json_result(page1), json_result(page2)]}
    )

    result = fetch_board(
        http,
        company(WatchAts.WORKDAY, token=WD_TOKEN, name="NVIDIA"),
        ["intern"],
        now=NOW,
    )

    assert result.error is None
    assert result.complete is False  # search results are not the whole board
    assert len(result.postings) == 19 + 3
    assert {p.source for p in result.postings} == {PostingSource.WORKDAY}
    assert {p.company for p in result.postings} == {"NVIDIA"}
    assert all(p.source_key.startswith(WD_TOKEN + "/job/") for p in result.postings)
    assert all(
        p.url.startswith(f"https://{WD_HOST}/{WD_SITE}/job/") for p in result.postings
    )
    assert [c.body for c in http.calls] == [
        {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"},
        {"appliedFacets": {}, "limit": 20, "offset": 20, "searchText": "intern"},
    ]
    assert {(c.method, c.url, c.max_bytes, c.timeout) for c in http.calls} == {
        ("POST", WD_JOBS_API, LIST_MAX_BYTES, DEFAULT_TIMEOUT)
    }


def test_fetch_board_workday_stops_at_200_per_keyword():
    pages = {"intern": [[wd_row(i * 20 + j) for j in range(20)] for i in range(50)]}
    http = FakeDiscoveryHttp(
        {("POST", WD_JOBS_API): workday_responder(pages, {"intern": 1000})}
    )

    result = fetch_board(
        http, company(WatchAts.WORKDAY, token=WD_TOKEN), ["intern"], now=NOW
    )

    assert result.error is None
    assert len(result.postings) == WORKDAY_MAX_PER_KEYWORD == 200
    assert [c.body["offset"] for c in http.calls] == list(range(0, 200, 20))


def test_fetch_board_workday_stops_on_an_empty_page():
    pages = {"intern": [[wd_row(j) for j in range(20)]]}  # claims 100, only 20 exist
    http = FakeDiscoveryHttp(
        {("POST", WD_JOBS_API): workday_responder(pages, {"intern": 100})}
    )
    result = fetch_board(
        http, company(WatchAts.WORKDAY, token=WD_TOKEN), ["intern"], now=NOW
    )
    assert len(result.postings) == 20
    assert [c.body["offset"] for c in http.calls] == [0, 20]


def test_fetch_board_workday_merges_keywords_by_source_key():
    pages = {
        "intern": [[wd_row(1), wd_row(2)]],
        "co-op": [[wd_row(2), wd_row(3)]],
    }
    http = FakeDiscoveryHttp(
        {("POST", WD_JOBS_API): workday_responder(pages, {"intern": 2, "co-op": 2})}
    )
    result = fetch_board(
        http,
        company(WatchAts.WORKDAY, token=WD_TOKEN),
        ["intern", "Intern ", "co-op", " "],
        now=NOW,
    )
    assert result.error is None
    assert len(result.postings) == 3
    assert len({p.source_key for p in result.postings}) == 3
    # duplicate and blank keywords are searched once / not at all
    assert [c.body["searchText"] for c in http.calls] == ["intern", "co-op"]


def test_fetch_board_workday_without_keywords_searches_once_with_empty_text():
    pages = {"": [[wd_row(1)]]}
    http = FakeDiscoveryHttp({("POST", WD_JOBS_API): workday_responder(pages, {"": 1})})
    result = fetch_board(http, company(WatchAts.WORKDAY, token=WD_TOKEN), [], now=NOW)
    assert len(result.postings) == 1
    assert [c.body["searchText"] for c in http.calls] == [""]


def test_fetch_board_workday_failure_on_a_later_page_fails_the_source():
    http = FakeDiscoveryHttp(
        {
            ("POST", WD_JOBS_API): [
                json_result(
                    {"total": 40, "jobPostings": [wd_row(j) for j in range(20)]}
                ),
                DiscoveryFetchError(f"{WD_HOST}/wday: status 500", status=500),
            ]
        }
    )
    result = fetch_board(
        http,
        company(WatchAts.WORKDAY, token=WD_TOKEN, name="NVIDIA"),
        ["intern"],
        now=NOW,
    )
    assert_failed(result, "NVIDIA", "status 500")


@pytest.mark.parametrize("data", [[], {"total": 3}, {"jobPostings": "x"}, "oops"])
def test_fetch_board_workday_malformed_page_fails_the_source(data):
    http = FakeDiscoveryHttp({("POST", WD_JOBS_API): json_result(data)})
    result = fetch_board(
        http,
        company(WatchAts.WORKDAY, token=WD_TOKEN, name="NVIDIA"),
        ["intern"],
        now=NOW,
    )
    assert_failed(result, "NVIDIA", "unexpected response")


def test_fetch_board_workday_body_is_fresh_per_request():
    http = FakeDiscoveryHttp(
        {
            ("POST", WD_JOBS_API): workday_responder(
                {"intern": [[wd_row(j) for j in range(20)], [wd_row(99)]]},
                {"intern": 21},
            )
        }
    )
    fetch_board(http, company(WatchAts.WORKDAY, token=WD_TOKEN), ["intern"], now=NOW)
    assert http.calls[0].body is not http.calls[1].body
    assert http.calls[0].body["offset"] == 0


# --- fetch_pasted ------------------------------------------------------------


def test_fetch_pasted_greenhouse_job_reads_the_single_job_api():
    api = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345001"
    http = FakeDiscoveryHttp(
        {("GET", api): json_result(load_json("greenhouse_job.json"))}
    )

    details = fetch_pasted(
        http, "https://job-boards.greenhouse.io/acme/jobs/4012345001?gh_src=x"
    )

    assert details.source is PostingSource.GREENHOUSE
    assert details.source_key == "4012345001"
    assert details.title == "Software Engineering Intern, Summer 2027"
    assert details.company == "Acme Robotics"
    assert http.calls == [
        FakeCall(
            "GET", api, etag=None, max_bytes=PAGE_MAX_BYTES, timeout=DEFAULT_TIMEOUT
        )
    ]


def test_fetch_pasted_lever_job_reads_the_single_job_api():
    job_id = "5ac21346-8e0c-4494-8e7a-3eb92ff77902"
    api = f"https://api.lever.co/v0/postings/acme/{job_id}"
    http = FakeDiscoveryHttp({("GET", api): json_result(load_json("lever_job.json"))})

    details = fetch_pasted(http, f"https://jobs.lever.co/acme/{job_id.upper()}/apply")

    assert details.source is PostingSource.LEVER
    assert details.source_key == job_id
    assert details.locations == ["Toronto, ON", "Waterloo, ON"]
    assert urls(http) == [("GET", api)]


def test_fetch_pasted_ashby_job_reads_the_board_and_finds_the_job():
    job_id = "2bb6be67-d1a8-42f7-bb1b-64ee36bf613f"
    http = FakeDiscoveryHttp(
        {("GET", ASHBY_BOARD_API): json_result(load_json("ashby_board.json"))}
    )

    details = fetch_pasted(http, f"https://jobs.ashbyhq.com/acme/{job_id}")

    assert details.source is PostingSource.ASHBY
    assert details.source_key == job_id
    assert details.title == "Research Engineer Intern"
    assert http.calls == [
        FakeCall(
            "GET",
            ASHBY_BOARD_API,
            etag=None,
            max_bytes=LIST_MAX_BYTES,
            timeout=DEFAULT_TIMEOUT,
        )
    ]


def test_fetch_pasted_ashby_job_missing_from_board_raises_readable_error():
    http = FakeDiscoveryHttp({("GET", ASHBY_BOARD_API): json_result({"jobs": []})})
    with pytest.raises(DiscoveryFetchError, match="Couldn't find that job"):
        fetch_pasted(
            http, "https://jobs.ashbyhq.com/acme/00000000-0000-0000-0000-000000000000"
        )


def test_fetch_pasted_workday_job_reads_the_detail_api():
    path = "job/US-CA-Santa-Clara/Intern_JR1"
    api = f"https://{WD_HOST}/wday/cxs/nvidia/{WD_SITE}/{path}"
    http = FakeDiscoveryHttp(
        {("GET", api): json_result(load_json("workday_job_detail.json"))}
    )

    details = fetch_pasted(http, f"https://{WD_HOST}/en-US/{WD_SITE}/{path}", now=NOW)

    assert details.source is PostingSource.WORKDAY
    assert details.source_key == f"{WD_TOKEN}/{path}"
    assert details.title == "Software Engineering Intern - Summer 2027"
    assert http.calls == [
        FakeCall(
            "GET", api, etag=None, max_bytes=PAGE_MAX_BYTES, timeout=DEFAULT_TIMEOUT
        )
    ]


def test_fetch_pasted_other_page_reads_jsonld():
    url = "https://careers.example.com/jobs/123"
    http = FakeDiscoveryHttp(
        {("PAGE", url): page_result(load_text("jobposting_page.html"), url=url)}
    )

    details = fetch_pasted(http, url)

    assert details.source is PostingSource.PASTED
    assert details.title
    assert http.calls == [
        FakeCall("PAGE", url, max_bytes=PAGE_MAX_BYTES, timeout=DEFAULT_TIMEOUT)
    ]


def test_fetch_pasted_page_keys_on_the_pasted_url_not_the_redirect_target():
    url = "https://careers.example.com/jobs/123?utm_source=x"
    http = FakeDiscoveryHttp(
        {
            ("PAGE", url): page_result(
                load_text("title_only_page.html"), url="https://other.example.net/x"
            )
        }
    )
    details = fetch_pasted(http, url)
    assert details.source_key == "https://careers.example.com/jobs/123"


def test_fetch_pasted_board_page_that_is_not_a_job_falls_back_to_the_page():
    url = "https://boards.greenhouse.io/acme"
    http = FakeDiscoveryHttp(
        {("PAGE", url): page_result(load_text("title_only_page.html"), url=url)}
    )
    details = fetch_pasted(http, url)
    assert details.source is PostingSource.PASTED
    assert urls(http) == [("PAGE", url)]


@pytest.mark.parametrize(
    ("url", "key"),
    [
        (
            "https://careers.example.com/jobs/1",
            ("PAGE", "https://careers.example.com/jobs/1"),
        ),
        (
            "https://boards.greenhouse.io/acme/jobs/42",
            ("GET", "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"),
        ),
    ],
)
def test_fetch_pasted_http_status_becomes_a_readable_error(url, key):
    http = FakeDiscoveryHttp(
        {key: DiscoveryFetchError("x.test/y: status 403", status=403)}
    )
    with pytest.raises(DiscoveryFetchError) as info:
        fetch_pasted(http, url)
    assert str(info.value) == "Couldn't read that page (status 403)"
    assert info.value.status == 403


def test_fetch_pasted_transport_error_becomes_a_readable_error():
    url = "https://careers.example.com/jobs/1"
    http = FakeDiscoveryHttp(
        {("PAGE", url): DiscoveryFetchError("careers.example.com: address not allowed")}
    )
    with pytest.raises(
        DiscoveryFetchError,
        match=r"^Couldn't read that page \(.*address not allowed\)$",
    ):
        fetch_pasted(http, url)


def test_fetch_pasted_board_payload_without_a_job_raises_readable_error():
    api = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"
    http = FakeDiscoveryHttp({("GET", api): json_result({"error": "nope"})})
    with pytest.raises(DiscoveryFetchError, match="Couldn't find that job"):
        fetch_pasted(http, "https://boards.greenhouse.io/acme/jobs/42")


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "ftp://x.test/a", "not a url", ""]
)
def test_fetch_pasted_refuses_non_http_links_without_any_request(url):
    http = FakeDiscoveryHttp()
    with pytest.raises(DiscoveryFetchError, match="http or https"):
        fetch_pasted(http, url)
    assert http.calls == []
