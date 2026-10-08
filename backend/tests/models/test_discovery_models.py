import pytest
from sqlalchemy.exc import IntegrityError

from app.models.app_settings import AppSettings
from app.models.application import Application
from app.models.posting import Posting, PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany

SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
VANSHB03_URL = "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json"


def _posting(**overrides) -> Posting:
    fields = dict(
        source=PostingSource.SIMPLIFY,
        source_key="abc-123",
        company="Stripe",
        title="Software Engineer Intern",
        url="https://stripe.com/jobs/1",
        url_key="https://stripe.com/jobs/1",
    )
    fields.update(overrides)
    return Posting(**fields)


def test_enum_values_are_lowercase():
    assert [s.value for s in PostingSource] == [
        "simplify", "vanshb03", "list", "greenhouse", "lever", "ashby", "workday", "pasted",
    ]
    assert [s.value for s in PostingState] == ["new", "saved", "dismissed", "applied"]
    assert [a.value for a in WatchAts] == ["greenhouse", "lever", "ashby", "workday"]


def test_posting_defaults(db_session):
    p = _posting()
    db_session.add(p)
    db_session.flush()
    db_session.refresh(p)
    assert p.state == PostingState.NEW
    assert p.closed is False
    assert p.locations == [] and p.terms == []
    assert p.category is None and p.sponsorship is None and p.date_posted is None
    assert p.first_seen_at is not None and p.last_seen_at is not None and p.state_changed_at is not None
    assert p.application_id is None and p.watch_company_id is None
    assert p.claude_score is None and p.claude_note is None


def test_posting_server_defaults(db_session):
    db_session.connection().exec_driver_sql(
        "INSERT INTO postings (source, source_key, company, title, url, url_key)"
        " VALUES ('greenhouse', 'raw-1', 'Acme', 'Intern', 'https://a.co/1', 'https://a.co/1')"
    )
    row = db_session.connection().exec_driver_sql(
        "SELECT locations, terms, closed, state::text, first_seen_at IS NOT NULL,"
        " last_seen_at IS NOT NULL, state_changed_at IS NOT NULL FROM postings WHERE source_key = 'raw-1'"
    ).one()
    assert tuple(row) == ([], [], False, "new", True, True, True)


def test_posting_source_and_key_unique(db_session):
    db_session.add(_posting())
    db_session.flush()
    db_session.add(_posting(url="https://stripe.com/jobs/2", url_key="https://stripe.com/jobs/2"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_source_key_from_another_source_is_allowed(db_session):
    db_session.add_all([_posting(), _posting(source=PostingSource.VANSHB03)])
    db_session.flush()


def test_posting_application_link_nulls_on_application_delete(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    p = _posting(application_id=app.id, state=PostingState.APPLIED)
    db_session.add(p)
    db_session.flush()
    db_session.delete(app)
    db_session.flush()
    db_session.refresh(p)
    assert p.application_id is None


def test_posting_watch_company_link_nulls_on_watch_company_delete(db_session):
    wc = WatchCompany(
        name="Stripe", ats=WatchAts.GREENHOUSE, board_token="stripe",
        careers_url="https://boards.greenhouse.io/stripe",
    )
    db_session.add(wc)
    db_session.flush()
    p = _posting(source=PostingSource.GREENHOUSE, watch_company_id=wc.id)
    db_session.add(p)
    db_session.flush()
    db_session.connection().exec_driver_sql("DELETE FROM watch_companies WHERE id = %s", (wc.id,))
    db_session.refresh(p)
    assert p.watch_company_id is None


def test_watch_company_defaults_and_uniqueness(db_session):
    wc = WatchCompany(
        name="NVIDIA", ats=WatchAts.WORKDAY,
        board_token="nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite",
        careers_url="https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    )
    db_session.add(wc)
    db_session.flush()
    db_session.refresh(wc)
    assert wc.added_at is not None
    assert wc.last_checked_at is None and wc.last_error is None
    db_session.add(WatchCompany(
        name="NVIDIA again", ats=WatchAts.WORKDAY, board_token=wc.board_token, careers_url=wc.careers_url,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_board_token_on_another_ats_is_allowed(db_session):
    db_session.add_all([
        WatchCompany(name="A", ats=WatchAts.GREENHOUSE, board_token="acme", careers_url="https://x/1"),
        WatchCompany(name="A", ats=WatchAts.LEVER, board_token="acme", careers_url="https://x/2"),
    ])
    db_session.flush()


EXPECTED_DISCOVERY_DEFAULTS = {
    "discovery_list_urls": [SIMPLIFY_URL, VANSHB03_URL],
    "discovery_terms": ["Summer 2027"],
    "discovery_categories": ["Software", "AI/ML/Data"],
    "discovery_include_keywords": [],
    "discovery_watchlist_keywords": ["intern", "internship", "co-op"],
    "discovery_exclude_keywords": ["senior", "staff", "principal", "phd"],
    "discovery_locations": [],
    "discovery_hide_no_sponsorship": False,
    "discovery_scan_hours": 6,
    "discovery_list_etags": {},
    "last_scan_at": None,
    "last_scan_error": None,
}


def test_settings_discovery_defaults(db_session):
    s = AppSettings(id=1)
    db_session.add(s)
    db_session.flush()
    db_session.refresh(s)
    assert {k: getattr(s, k) for k in EXPECTED_DISCOVERY_DEFAULTS} == EXPECTED_DISCOVERY_DEFAULTS


def test_settings_discovery_server_defaults(db_session):
    db_session.connection().exec_driver_sql("INSERT INTO app_settings (id) VALUES (1)")
    s = db_session.get(AppSettings, 1)
    assert {k: getattr(s, k) for k in EXPECTED_DISCOVERY_DEFAULTS} == EXPECTED_DISCOVERY_DEFAULTS

