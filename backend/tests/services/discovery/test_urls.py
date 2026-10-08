import pytest

from app.models.watch_company import WatchAts
from app.services.discovery.urls import (
    KNOWN_CUSTOM_SITES,
    BoardRef,
    JobRef,
    board_careers_url,
    known_custom_site,
    normalize_url,
    parse_board_url,
    parse_job_url,
    safe_http_url,
)

LEVER_ID = "b4711825-bb32-4704-b8f1-1d2538cad4f8"
ASHBY_ID = "2bb6be67-d1a8-42f7-bb1b-64ee36bf613f"
NVIDIA = "nvidia.wd5.myworkdayjobs.com"


# --- normalize_url -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.COM/Jobs/123", "https://example.com/Jobs/123"),
        ("HTTPS://example.com/a", "https://example.com/a"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com", "https://example.com"),
        ("https://example.com/a#apply", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://user:pw@example.com/a", "https://example.com/a"),
        (
            "https://example.com/a?utm_source=x&UTM_Medium=y&utm_campaign=z",
            "https://example.com/a",
        ),
        ("https://example.com/a?ref=simplify&source=list", "https://example.com/a"),
        ("https://jobs.lever.co/x/1?lever-source=a&lever-origin=b", "https://jobs.lever.co/x/1"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?b=2&utm_source=x&a=1#f", "https://example.com/a?a=1&b=2"),
        # gh_src is a tracking param everywhere.
        (
            "https://example.com/careers?gh_jid=55&gh_src=abc",
            "https://example.com/careers?gh_jid=55",
        ),
        # On Greenhouse's own hosts the job id is in the path, so gh_jid is redundant.
        (
            "https://job-boards.greenhouse.io/transcarent/jobs/5822302004?gh_jid=5822302004",
            "https://job-boards.greenhouse.io/transcarent/jobs/5822302004",
        ),
        (
            "https://boards.greenhouse.io/acme/jobs/1?gh_jid=1&gh_src=x",
            "https://boards.greenhouse.io/acme/jobs/1",
        ),
        # Elsewhere gh_jid is often the only job identifier: keep it.
        (
            "https://careers.withwaymo.com/jobs?gh_jid=7001",
            "https://careers.withwaymo.com/jobs?gh_jid=7001",
        ),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_normalize_url_distinct_gh_jid_on_custom_domains_stay_distinct():
    a = normalize_url("https://careers.withwaymo.com/jobs?gh_jid=1")
    b = normalize_url("https://careers.withwaymo.com/jobs?gh_jid=2")
    assert a != b


def test_normalize_url_tracking_variants_share_a_key():
    a = normalize_url("https://Example.com/job/1/?utm_source=simplify#top")
    b = normalize_url("https://example.com/job/1?ref=vanshb03")
    assert a == b == "https://example.com/job/1"


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "ftp://example.com/file",
        "data:text/html,hi",
        "mailto:jobs@example.com",
        "/relative/path",
        "example.com/jobs",
        "//example.com/jobs",
        "https://",
        "https:///path",
        "https://example.com:notaport/a",
        "",
        "   ",
    ],
)
def test_normalize_url_rejects(raw):
    assert normalize_url(raw) is None


# --- safe_http_url -----------------------------------------------------------


def test_safe_http_url_accepts_and_strips():
    assert safe_http_url("  https://example.com/a?b=1  ") == "https://example.com/a?b=1"
    assert safe_http_url("http://example.com") == "http://example.com"


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "ftp://example.com",
        "/jobs/1",
        "https://",
        "https://exa mple.com/a",
        "https://example.com/a\nb",
        "https://example.com/" + "a" * 2000,
        "",
    ],
)
def test_safe_http_url_rejects(raw):
    assert safe_http_url(raw) is None


def test_safe_http_url_accepts_exactly_2000_chars():
    url = "https://example.com/" + "a" * (2000 - len("https://example.com/"))
    assert len(url) == 2000
    assert safe_http_url(url) == url


def test_safe_http_url_rejects_non_string():
    assert safe_http_url(None) is None  # type: ignore[arg-type]
    assert safe_http_url(123) is None  # type: ignore[arg-type]


# --- parse_board_url ---------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/stripe", BoardRef(WatchAts.GREENHOUSE, "stripe")),
        ("https://boards.greenhouse.io/stripe/", BoardRef(WatchAts.GREENHOUSE, "stripe")),
        ("http://Boards.Greenhouse.io/stripe", BoardRef(WatchAts.GREENHOUSE, "stripe")),
        ("https://job-boards.greenhouse.io/prolaio", BoardRef(WatchAts.GREENHOUSE, "prolaio")),
        (
            "https://job-boards.greenhouse.io/prolaio/jobs/5115101008",
            BoardRef(WatchAts.GREENHOUSE, "prolaio"),
        ),
        (
            "https://boards.greenhouse.io/embed/job_board?for=figma",
            BoardRef(WatchAts.GREENHOUSE, "figma"),
        ),
        ("https://jobs.lever.co/fullscript", BoardRef(WatchAts.LEVER, "fullscript")),
        (
            f"https://jobs.lever.co/fullscript/{LEVER_ID}/apply",
            BoardRef(WatchAts.LEVER, "fullscript"),
        ),
        ("https://jobs.ashbyhq.com/charge-robotics", BoardRef(WatchAts.ASHBY, "charge-robotics")),
        ("https://jobs.ashbyhq.com/open_ai?x=1", BoardRef(WatchAts.ASHBY, "open_ai")),
        (
            f"https://{NVIDIA}/NVIDIAExternalCareerSite",
            BoardRef(WatchAts.WORKDAY, f"{NVIDIA}/nvidia/NVIDIAExternalCareerSite"),
        ),
        (
            f"https://{NVIDIA}/en-US/NVIDIAExternalCareerSite",
            BoardRef(WatchAts.WORKDAY, f"{NVIDIA}/nvidia/NVIDIAExternalCareerSite"),
        ),
        (
            f"https://{NVIDIA}/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Intern_JR1",
            BoardRef(WatchAts.WORKDAY, f"{NVIDIA}/nvidia/NVIDIAExternalCareerSite"),
        ),
        (
            "https://globalhr.wd5.myworkdayjobs.com/fr-CA/Private_Posting/job/X/Y",
            BoardRef(WatchAts.WORKDAY, "globalhr.wd5.myworkdayjobs.com/globalhr/Private_Posting"),
        ),
        (
            "https://intel.wd1.myworkdayjobs.com/en/External",
            BoardRef(WatchAts.WORKDAY, "intel.wd1.myworkdayjobs.com/intel/External"),
        ),
        (
            "https://Salesforce.WD12.myworkdayjobs.com/External_Career_Site",
            BoardRef(
                WatchAts.WORKDAY,
                "salesforce.wd12.myworkdayjobs.com/salesforce/External_Career_Site",
            ),
        ),
        # A two-letter site name followed by /job/ is the site, not a locale.
        (
            "https://acme.wd1.myworkdayjobs.com/IT/job/Remote/Intern_R1",
            BoardRef(WatchAts.WORKDAY, "acme.wd1.myworkdayjobs.com/acme/IT"),
        ),
    ],
)
def test_parse_board_url(url, expected):
    assert parse_board_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/",
        "https://boards.greenhouse.io/../x",
        "https://boards.greenhouse.io/%2e%2e%2fx",
        "https://boards.greenhouse.io/a.b",
        "https://boards.greenhouse.io/embed/job_board",
        "https://boards.greenhouse.io/embed/job_board?for=../x",
        "https://boards.greenhouse.io/" + "a" * 101,
        "https://jobs.lever.co/",
        "https://jobs.lever.co/bad%20token",
        "https://jobs.ashbyhq.com/",
        "https://jobs.ashbyhq.com/x y",
        "https://evil.com/boards.greenhouse.io/stripe",
        "https://boards.greenhouse.io.evil.com/stripe",
        "https://notboards.greenhouse.io/stripe",
        "https://nvidia.wd5.myworkdayjobs.com/",
        "https://nvidia.wd5.myworkdayjobs.com/en-US",
        "https://nvidia.wd5.myworkdayjobs.com/en-US/../x",
        "https://nvidia.wd5.myworkdayjobs.com.evil.com/External",
        "https://nvidia.wdx.myworkdayjobs.com/External",
        "https://a.b.wd5.myworkdayjobs.com/External",
        "https://nvidia.wd5.myworkdayjobs.com/bad.site",
        "javascript:alert(1)",
        "ftp://boards.greenhouse.io/stripe",
        "not a url",
        "https://careers.google.com/jobs",
    ],
)
def test_parse_board_url_rejects(url):
    assert parse_board_url(url) is None


# --- parse_job_url -----------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://boards.greenhouse.io/intrinsicrobotics/jobs/5795490004",
            JobRef(WatchAts.GREENHOUSE, "intrinsicrobotics", "5795490004"),
        ),
        (
            "https://job-boards.greenhouse.io/transcarent/jobs/5822302004?gh_jid=5822302004",
            JobRef(WatchAts.GREENHOUSE, "transcarent", "5822302004"),
        ),
        (
            "https://boards.greenhouse.io/embed/job_app?for=figma&token=7625508",
            JobRef(WatchAts.GREENHOUSE, "figma", "7625508"),
        ),
        (
            f"https://jobs.lever.co/fullscript/{LEVER_ID}",
            JobRef(WatchAts.LEVER, "fullscript", LEVER_ID),
        ),
        (
            f"https://jobs.lever.co/fullscript/{LEVER_ID.upper()}/apply",
            JobRef(WatchAts.LEVER, "fullscript", LEVER_ID),
        ),
        (
            f"https://jobs.ashbyhq.com/circleback/{ASHBY_ID}/application?embed=true",
            JobRef(WatchAts.ASHBY, "circleback", ASHBY_ID),
        ),
        (
            f"https://jobs.ashbyhq.com/circleback/{ASHBY_ID}",
            JobRef(WatchAts.ASHBY, "circleback", ASHBY_ID),
        ),
        (
            "https://fhlbny.wd1.myworkdayjobs.com/FHLBNY/job/New-York/Intern---Financial-Risk_R677",
            JobRef(
                WatchAts.WORKDAY,
                "fhlbny.wd1.myworkdayjobs.com/fhlbny/FHLBNY",
                "job/New-York/Intern---Financial-Risk_R677",
            ),
        ),
        (
            f"https://{NVIDIA}/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Intern_JR1999",
            JobRef(
                WatchAts.WORKDAY,
                f"{NVIDIA}/nvidia/NVIDIAExternalCareerSite",
                "job/US-CA-Santa-Clara/Intern_JR1999",
            ),
        ),
        (
            "https://ensemblehp.wd5.myworkdayjobs.com/ensemblehealthpartnerscareers/job/Engineering-Intern_R041252",
            JobRef(
                WatchAts.WORKDAY,
                "ensemblehp.wd5.myworkdayjobs.com/ensemblehp/ensemblehealthpartnerscareers",
                "job/Engineering-Intern_R041252",
            ),
        ),
    ],
)
def test_parse_job_url(url, expected):
    assert parse_job_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/stripe",
        "https://boards.greenhouse.io/stripe/jobs/abc",
        "https://boards.greenhouse.io/stripe/jobs/",
        "https://boards.greenhouse.io/../jobs/123",
        "https://boards.greenhouse.io/embed/job_app?token=7625508",
        "https://boards.greenhouse.io/embed/job_app?for=figma&token=x1",
        "https://jobs.lever.co/fullscript",
        "https://jobs.lever.co/fullscript/not-a-uuid",
        f"https://jobs.lever.co/fullscript/{LEVER_ID}/other",
        "https://jobs.ashbyhq.com/circleback",
        "https://jobs.ashbyhq.com/circleback/123",
        f"https://{NVIDIA}/NVIDIAExternalCareerSite",
        f"https://{NVIDIA}/NVIDIAExternalCareerSite/job",
        f"https://{NVIDIA}/NVIDIAExternalCareerSite/job/a/b/c",
        f"https://{NVIDIA}/NVIDIAExternalCareerSite/job/../x",
        f"https://{NVIDIA}/NVIDIAExternalCareerSite/job/a%2Fb",
        "https://tmobile.wd1.myworkdayjobs.com/en-US/External/details/Intern_REQ342273",
        "https://example.com/jobs/123",
        "javascript:alert(1)",
    ],
)
def test_parse_job_url_rejects(url):
    assert parse_job_url(url) is None


# --- known custom sites ------------------------------------------------------


def test_known_custom_sites_cover_the_big_five():
    assert set(KNOWN_CUSTOM_SITES.values()) >= {"Google", "Microsoft", "Apple", "Meta", "Amazon"}
    for suffix in (
        "google.com",
        "careers.google.com",
        "microsoft.com",
        "apple.com",
        "metacareers.com",
        "amazon.jobs",
    ):
        assert suffix in KNOWN_CUSTOM_SITES


@pytest.mark.parametrize(
    ("url", "company"),
    [
        ("https://careers.google.com/jobs/results/123", "Google"),
        ("https://www.google.com/about/careers/applications/jobs/results/1", "Google"),
        ("https://jobs.careers.microsoft.com/global/en/job/1", "Microsoft"),
        ("https://jobs.apple.com/en-us/details/1", "Apple"),
        ("https://www.metacareers.com/jobs/1", "Meta"),
        ("https://www.amazon.jobs/en/jobs/1", "Amazon"),
        ("https://AMAZON.JOBS/en", "Amazon"),
    ],
)
def test_known_custom_site(url, company):
    assert known_custom_site(url) == company


@pytest.mark.parametrize(
    "url",
    [
        "https://notgoogle.com/jobs",
        "https://google.com.evil.com/jobs",
        "https://boards.greenhouse.io/stripe",
        "javascript:alert(1)",
        "",
    ],
)
def test_known_custom_site_rejects(url):
    assert known_custom_site(url) is None


# --- backslash (browser/urlsplit disagreement) -------------------------------

BACKSLASH_URLS = [
    "https://evil.com\\@acme.wd5.myworkdayjobs.com/Site",
    "https://evil.com\\@boards.greenhouse.io/stripe",
    "https://boards.greenhouse.io\\stripe",
    "https://example.com/a\\b",
]


@pytest.mark.parametrize("url", BACKSLASH_URLS)
def test_backslash_urls_are_rejected_everywhere(url):
    assert "\\" in url
    assert safe_http_url(url) is None
    assert normalize_url(url) is None
    assert parse_board_url(url) is None
    assert parse_job_url(url) is None
    assert known_custom_site(url) is None


# --- board_careers_url --------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (BoardRef(WatchAts.GREENHOUSE, "stripe"), "https://job-boards.greenhouse.io/stripe"),
        (BoardRef(WatchAts.LEVER, "fullscript"), "https://jobs.lever.co/fullscript"),
        (BoardRef(WatchAts.ASHBY, "open_ai"), "https://jobs.ashbyhq.com/open_ai"),
        (
            BoardRef(WatchAts.WORKDAY, f"{NVIDIA}/nvidia/NVIDIAExternalCareerSite"),
            f"https://{NVIDIA}/NVIDIAExternalCareerSite",
        ),
        (
            BoardRef(WatchAts.WORKDAY, "acme.wd1.myworkdayjobs.com/acme/IT"),
            "https://acme.wd1.myworkdayjobs.com/en-US/IT",
        ),
    ],
)
def test_board_careers_url_round_trips(ref, expected):
    assert board_careers_url(ref) == expected
    assert parse_board_url(expected) == ref


@pytest.mark.parametrize(
    "pasted",
    [
        "https://boards.greenhouse.io/embed/job_board?for=figma&utm_source=x",
        "http://Boards.Greenhouse.io/stripe/jobs/123?gh_src=abc#apply",
        f"https://jobs.lever.co/fullscript/{LEVER_ID}/apply",
        f"https://{NVIDIA}/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Intern_JR1",
    ],
)
def test_board_careers_url_from_any_recognized_paste(pasted):
    ref = parse_board_url(pasted)
    assert ref is not None
    assert parse_board_url(board_careers_url(ref)) == ref


@pytest.mark.parametrize(
    "ref",
    [
        BoardRef(WatchAts.GREENHOUSE, "../x"),
        BoardRef(WatchAts.LEVER, ""),
        BoardRef(WatchAts.ASHBY, "a/b"),
        BoardRef(WatchAts.WORKDAY, "evil.com/evil/Site"),
        BoardRef(WatchAts.WORKDAY, "acme.wd1.myworkdayjobs.com/other/Site"),
        BoardRef(WatchAts.WORKDAY, "acme.wd1.myworkdayjobs.com/acme"),
        BoardRef(WatchAts.WORKDAY, "acme.wd1.myworkdayjobs.com/acme/../x"),
    ],
)
def test_board_careers_url_rejects_malformed_refs(ref):
    with pytest.raises(ValueError):
        board_careers_url(ref)
