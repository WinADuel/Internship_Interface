"""Watchlist service (Phase 2 spec §2b; plan Task 8)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models.posting import Posting, PostingSource, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.schemas.discovery import WatchCompanyIn, WatchCompanyOut
from app.services.discovery import watchlist
from app.services.discovery.filters import DiscoveryFilters
from app.services.errors import (
    DuplicateWatchCompanyError,
    UnsupportedCareersSiteError,
    WatchCompanyNotFoundError,
)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def add(db, url: str, name: str | None = None) -> WatchCompany:
    return watchlist.add_company(db, WatchCompanyIn(careers_url=url, name=name))


@pytest.mark.parametrize(
    ("url", "ats", "token", "careers_url", "name"),
    [
        (
            "https://boards.greenhouse.io/openai?gh_src=abc",
            WatchAts.GREENHOUSE,
            "openai",
            "https://job-boards.greenhouse.io/openai",
            "Openai",
        ),
        (
            "https://job-boards.greenhouse.io/acme-robotics/jobs/123",
            WatchAts.GREENHOUSE,
            "acme-robotics",
            "https://job-boards.greenhouse.io/acme-robotics",
            "Acme Robotics",
        ),
        (
            "https://jobs.lever.co/palantir/?lever-source=x",
            WatchAts.LEVER,
            "palantir",
            "https://jobs.lever.co/palantir",
            "Palantir",
        ),
        (
            "https://jobs.ashbyhq.com/ramp#jobs",
            WatchAts.ASHBY,
            "ramp",
            "https://jobs.ashbyhq.com/ramp",
            "Ramp",
        ),
        (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite?q=intern",
            WatchAts.WORKDAY,
            "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite",
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            "Nvidia",
        ),
    ],
)
def test_add_company_recognizes_each_board_and_stores_the_canonical_url(
    db_session, url, ats, token, careers_url, name
):
    company = add(db_session, url)
    assert company.id is not None
    assert company.ats is ats
    assert company.board_token == token
    assert company.careers_url == careers_url
    assert company.name == name
    assert company.last_checked_at is None and company.last_error is None


def test_add_company_uses_the_given_name(db_session):
    company = add(db_session, "https://jobs.lever.co/palantir", name="  Palantir  Technologies ")
    assert company.name == "Palantir Technologies"


def test_blank_name_falls_back_to_the_token(db_session):
    assert add(db_session, "https://jobs.lever.co/palantir", name="   ").name == "Palantir"


@pytest.mark.parametrize(
    ("url", "company"),
    [
        ("https://www.google.com/about/careers/applications/jobs/results", "Google"),
        ("https://careers.microsoft.com/v2/global/en/home.html", "Microsoft"),
        ("https://www.amazon.jobs/en/teams/internships", "Amazon"),
    ],
)
def test_custom_careers_site_gets_its_own_message(db_session, url, company):
    with pytest.raises(UnsupportedCareersSiteError) as exc:
        add(db_session, url)
    assert exc.value.message == (
        f"{company} uses its own careers site, so it can't be watched. Its internships come in "
        "through the community lists, and you can paste any of its postings."
    )
    assert list(db_session.scalars(select(WatchCompany))) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.example.com/jobs",
        "https://boards.greenhouse.io/",
        "javascript:alert(1)",
        "not a url",
        "",
    ],
)
def test_unknown_site_gets_the_generic_message(db_session, url):
    with pytest.raises(UnsupportedCareersSiteError) as exc:
        add(db_session, url)
    assert exc.value.message == (
        "That careers page isn't on Greenhouse, Lever, Ashby or Workday, so it can't be watched. "
        "You can still paste individual postings from it."
    )


def test_adding_the_same_board_twice_is_a_duplicate(db_session):
    add(db_session, "https://boards.greenhouse.io/openai")
    with pytest.raises(DuplicateWatchCompanyError):
        add(db_session, "https://job-boards.greenhouse.io/OpenAI/jobs/42", name="Other")
    assert len(list(db_session.scalars(select(WatchCompany)))) == 1


def test_same_token_on_another_board_is_not_a_duplicate(db_session):
    add(db_session, "https://boards.greenhouse.io/acme")
    add(db_session, "https://jobs.lever.co/acme")
    assert len(list(db_session.scalars(select(WatchCompany)))) == 2


def test_watch_company_input_caps():
    with pytest.raises(ValidationError):
        WatchCompanyIn(careers_url="https://jobs.lever.co/x", name="n" * 201)
    with pytest.raises(ValidationError):
        WatchCompanyIn(careers_url="https://jobs.lever.co/" + "x" * 5000)
    assert WatchCompanyIn(careers_url="https://jobs.lever.co/x", name="n" * 200).name == "n" * 200


# --- listing -----------------------------------------------------------------


def posting(db, company: WatchCompany | None, key: str, title: str, **kw) -> Posting:
    url = f"https://jobs.example.com/{key}"
    row = Posting(
        source=kw.pop("source", PostingSource.GREENHOUSE),
        source_key=key,
        company=company.name if company else "Other",
        title=title,
        locations=["Remote"],
        url=url,
        url_key=url,
        terms=[],
        watch_company_id=company.id if company else None,
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def test_list_companies_counts_open_matches_with_the_filters(db_session):
    db = db_session
    acme = add(db, "https://boards.greenhouse.io/acme")
    beta = add(db, "https://jobs.lever.co/beta")
    zeta = add(db, "https://jobs.ashbyhq.com/zeta", name="aardvark")  # sorts first by name
    posting(db, acme, "a1", "Software Intern")
    posting(db, acme, "a2", "Hardware Intern")
    posting(db, acme, "a3", "Staff Engineer")  # no watchlist keyword
    posting(db, acme, "a4", "Data Intern", closed=True)
    posting(db, acme, "a5", "Ops Intern", state=PostingState.SAVED)
    posting(db, acme, "a6", "Ops Intern 2", state=PostingState.DISMISSED)
    posting(db, beta, "b1", "Research Intern", source=PostingSource.LEVER)
    posting(db, None, "o1", "Software Intern")

    filters = DiscoveryFilters(watchlist_keywords=["intern"], exclude_keywords=["hardware"])
    rows = watchlist.list_companies(db, filters)

    assert [(c.id, n) for c, n in rows] == [(zeta.id, 0), (acme.id, 1), (beta.id, 1)]
    out = WatchCompanyOut.build(rows[1][0], rows[1][1])
    assert out.open_matches == 1 and out.board_token == "acme" and out.ats is WatchAts.GREENHOUSE


def test_list_companies_with_no_filters_counts_every_open_new_posting(db_session):
    acme = add(db_session, "https://boards.greenhouse.io/acme")
    posting(db_session, acme, "a1", "Software Intern")
    posting(db_session, acme, "a3", "Staff Engineer")
    assert [n for _, n in watchlist.list_companies(db_session, DiscoveryFilters())] == [2]


def test_list_companies_when_empty(db_session):
    assert watchlist.list_companies(db_session, DiscoveryFilters()) == []


# --- removing ----------------------------------------------------------------


def test_remove_company_keeps_its_postings(db_session):
    acme = add(db_session, "https://boards.greenhouse.io/acme")
    row = posting(db_session, acme, "a1", "Software Intern", state=PostingState.SAVED)

    watchlist.remove_company(db_session, acme.id)

    assert list(db_session.scalars(select(WatchCompany))) == []
    db_session.refresh(row)
    assert row.watch_company_id is None
    assert row.state is PostingState.SAVED


def test_remove_missing_company_raises_not_found(db_session):
    with pytest.raises(WatchCompanyNotFoundError):
        watchlist.remove_company(db_session, 999_999)
