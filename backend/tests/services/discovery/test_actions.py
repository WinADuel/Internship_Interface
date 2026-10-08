"""Posting actions and paste-a-link (Phase 2 spec §2c, §7; plan Task 8).

Everything runs against the test database; HTTP goes through
FakeDiscoveryHttp, so no test touches the network.
"""

import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.posting import Posting, PostingSource, PostingState
from app.models.research_queue import QueueKind, ResearchQueueItem
from app.models.status_history import StatusHistory
from app.models.watch_company import WatchAts, WatchCompany
from app.schemas.discovery import PasteConfirmIn, PastePreviewOut
from app.services.discovery import actions
from app.services.discovery.http import DiscoveryFetchError
from app.services.discovery.labels import SOURCE_LABELS, application_source
from app.services.discovery.parsers import workday_source_key
from app.services.discovery.urls import normalize_url
from app.services.errors import InvalidPostingStateError, PostingNotFoundError
from tests.services.discovery.fakes import FakeDiscoveryHttp, json_result, page_result

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=3)
TODAY = date(2026, 10, 8)

GH_JOB_URL = "https://job-boards.greenhouse.io/acme/jobs/4012345"
GH_JOB_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345"
LEVER_ID = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"
ASHBY_ID = "1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d"
WORKDAY_JOB_URL = (
    "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"
    "US-CA-Santa-Clara/Software-Intern_JR1"
)


def make_posting(
    db: Session,
    key: str = "1",
    *,
    state: PostingState = PostingState.NEW,
    source: PostingSource = PostingSource.SIMPLIFY,
    company: str = "Acme",
    title: str = "Software Intern",
    locations: list[str] | None = None,
    url: str | None = None,
    closed: bool = False,
    application_id: int | None = None,
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
        state=state,
        state_changed_at=EARLIER,
        first_seen_at=EARLIER,
        last_seen_at=EARLIER,
        closed=closed,
        application_id=application_id,
    )
    db.add(posting)
    db.commit()
    return posting


def all_postings(db: Session) -> list[Posting]:
    return list(db.scalars(select(Posting).order_by(Posting.id)))


def count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# --- simple transitions ------------------------------------------------------


@pytest.mark.parametrize("start", [PostingState.NEW, PostingState.DISMISSED])
def test_save_moves_new_or_dismissed_to_saved(db_session, start):
    posting = make_posting(db_session, state=start)
    result = actions.save(db_session, posting.id, NOW)
    assert result.id == posting.id
    db_session.refresh(posting)
    assert posting.state is PostingState.SAVED
    assert posting.state_changed_at == NOW


@pytest.mark.parametrize("start", [PostingState.NEW, PostingState.SAVED])
def test_dismiss_moves_new_or_saved_to_dismissed(db_session, start):
    posting = make_posting(db_session, state=start)
    actions.dismiss(db_session, posting.id, NOW)
    db_session.refresh(posting)
    assert posting.state is PostingState.DISMISSED
    assert posting.state_changed_at == NOW


def test_restore_moves_dismissed_to_new(db_session):
    posting = make_posting(db_session, state=PostingState.DISMISSED)
    actions.restore(db_session, posting.id, NOW)
    db_session.refresh(posting)
    assert posting.state is PostingState.NEW
    assert posting.state_changed_at == NOW


@pytest.mark.parametrize(
    ("action", "start", "message"),
    [
        (actions.save, PostingState.SAVED, "already saved"),
        (actions.save, PostingState.APPLIED, "already applied"),
        (actions.dismiss, PostingState.DISMISSED, "already dismissed"),
        (actions.dismiss, PostingState.APPLIED, "already applied"),
        (actions.restore, PostingState.NEW, "can't restore a posting that is new"),
        (actions.restore, PostingState.SAVED, "can't restore a posting that is saved"),
        (actions.restore, PostingState.APPLIED, "already applied"),
    ],
)
def test_invalid_transitions_raise_and_change_nothing(db_session, action, start, message):
    posting = make_posting(db_session, state=start)
    with pytest.raises(InvalidPostingStateError) as exc:
        action(db_session, posting.id, NOW)
    assert exc.value.message == message
    assert exc.value.state == start.value
    db_session.refresh(posting)
    assert posting.state is start
    assert posting.state_changed_at == EARLIER


@pytest.mark.parametrize("action", [actions.save, actions.dismiss, actions.restore])
def test_transitions_on_a_missing_posting_raise_not_found(db_session, action):
    with pytest.raises(PostingNotFoundError):
        action(db_session, 999_999, NOW)


def test_dismiss_many_dismisses_only_new_postings(db_session):
    new1 = make_posting(db_session, "1")
    new2 = make_posting(db_session, "2")
    saved = make_posting(db_session, "3", state=PostingState.SAVED)
    applied = make_posting(db_session, "4", state=PostingState.APPLIED)
    untouched = make_posting(db_session, "5")

    n = actions.dismiss_many(
        db_session, [new1.id, new2.id, new2.id, saved.id, applied.id, 999_999], NOW
    )

    assert n == 2
    for p in (new1, new2, saved, applied, untouched):
        db_session.refresh(p)
    assert new1.state is PostingState.DISMISSED and new1.state_changed_at == NOW
    assert new2.state is PostingState.DISMISSED
    assert saved.state is PostingState.SAVED and saved.state_changed_at == EARLIER
    assert applied.state is PostingState.APPLIED
    assert untouched.state is PostingState.NEW


def test_dismiss_many_with_no_ids_is_a_no_op(db_session):
    make_posting(db_session)
    assert actions.dismiss_many(db_session, [], NOW) == 0
    assert all_postings(db_session)[0].state is PostingState.NEW


# --- apply -------------------------------------------------------------------


def contacts_items(db: Session, application_id: int) -> list[ResearchQueueItem]:
    return list(
        db.scalars(
            select(ResearchQueueItem).where(
                ResearchQueueItem.application_id == application_id,
                ResearchQueueItem.kind == QueueKind.COMPANY_CONTACTS,
            )
        )
    )


def test_apply_creates_an_applied_application_from_the_posting(db_session):
    posting = make_posting(
        db_session,
        state=PostingState.SAVED,
        company="Stripe",
        title="SWE Intern",
        locations=["Seattle, WA", "Remote"],
        url="https://jobs.example.com/stripe/1",
    )

    application = actions.apply(db_session, posting.id, TODAY, now=NOW)

    assert application.id is not None
    assert application.status is ApplicationStatus.APPLIED
    assert application.date_applied == TODAY
    assert application.company == "Stripe"
    assert application.role_title == "SWE Intern"
    assert application.location == "Seattle, WA"
    assert application.job_link == "https://jobs.example.com/stripe/1"
    assert application.source == "Discover: Simplify"
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED
    assert posting.application_id == application.id
    assert posting.state_changed_at == NOW
    history = list(
        db_session.scalars(select(StatusHistory).where(StatusHistory.application_id == application.id))
    )
    assert [(h.old_status, h.new_status) for h in history] == [(None, ApplicationStatus.APPLIED)]
    assert len(contacts_items(db_session, application.id)) == 1


def test_apply_from_the_inbox_works_and_no_locations_means_no_location(db_session):
    posting = make_posting(db_session, state=PostingState.NEW, locations=[])
    application = actions.apply(db_session, posting.id, TODAY, now=NOW)
    assert application.location is None
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED


def test_apply_twice_creates_one_application_and_one_contacts_item(db_session):
    posting = make_posting(db_session, state=PostingState.SAVED)
    first = actions.apply(db_session, posting.id, TODAY, now=NOW)

    with pytest.raises(InvalidPostingStateError) as exc:
        actions.apply(db_session, posting.id, TODAY, now=NOW + timedelta(minutes=1))

    assert exc.value.message == "already applied"
    assert count(db_session, Application) == 1
    assert len(contacts_items(db_session, first.id)) == 1
    assert count(db_session, ResearchQueueItem) == 1
    db_session.refresh(posting)
    assert posting.application_id == first.id
    assert posting.state_changed_at == NOW


def test_apply_again_after_the_application_was_deleted(db_session):
    posting = make_posting(db_session, state=PostingState.SAVED)
    first = actions.apply(db_session, posting.id, TODAY, now=NOW)
    db_session.delete(first)
    db_session.commit()
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED and posting.application_id is None

    second = actions.apply(db_session, posting.id, TODAY, now=NOW)

    assert second.id != first.id
    db_session.refresh(posting)
    assert posting.application_id == second.id


def test_apply_from_dismissed_is_invalid(db_session):
    posting = make_posting(db_session, state=PostingState.DISMISSED)
    with pytest.raises(InvalidPostingStateError) as exc:
        actions.apply(db_session, posting.id, TODAY, now=NOW)
    assert exc.value.message == "can't apply to a posting that is dismissed"
    assert count(db_session, Application) == 0


def test_apply_to_a_missing_posting_raises_not_found(db_session):
    with pytest.raises(PostingNotFoundError):
        actions.apply(db_session, 999_999, TODAY, now=NOW)


@pytest.mark.parametrize(
    ("source", "label"),
    [
        (PostingSource.SIMPLIFY, "Simplify"),
        (PostingSource.VANSHB03, "vanshb03 list"),
        (PostingSource.LIST, "Community list"),
        (PostingSource.GREENHOUSE, "Greenhouse"),
        (PostingSource.LEVER, "Lever"),
        (PostingSource.ASHBY, "Ashby"),
        (PostingSource.WORKDAY, "Workday"),
        (PostingSource.PASTED, "Pasted"),
    ],
)
def test_apply_labels_the_application_source(db_session, source, label):
    assert application_source(source) == f"Discover: {label}"
    posting = make_posting(db_session, state=PostingState.SAVED, source=source)
    application = actions.apply(db_session, posting.id, TODAY, now=NOW)
    assert application.source == f"Discover: {label}"


def test_every_source_has_a_label():
    assert set(SOURCE_LABELS) == set(PostingSource)


# Concurrent Apply needs two real transactions, so this test commits through
# its own sessions and cleans up after itself.


@pytest.fixture()
def committed_posting(_engine):
    with Session(_engine) as s:
        posting = Posting(
            source=PostingSource.SIMPLIFY,
            source_key="concurrent-apply-test",
            company="Racecond",
            title="Concurrency Intern",
            locations=[],
            url="https://jobs.example.com/concurrent-apply-test",
            url_key="https://jobs.example.com/concurrent-apply-test",
            terms=[],
            state=PostingState.SAVED,
        )
        s.add(posting)
        s.commit()
        posting_id = posting.id
    yield posting_id
    with Session(_engine) as s:
        app_ids = list(
            s.scalars(select(Application.id).where(Application.company == "Racecond"))
        )
        s.execute(delete(Posting).where(Posting.id == posting_id))
        if app_ids:
            s.execute(delete(ResearchQueueItem).where(ResearchQueueItem.application_id.in_(app_ids)))
            s.execute(delete(StatusHistory).where(StatusHistory.application_id.in_(app_ids)))
            s.execute(delete(Application).where(Application.id.in_(app_ids)))
        s.commit()


def test_concurrent_apply_creates_one_application(_engine, committed_posting, monkeypatch):
    """The first Apply holds the posting's row lock until it commits; the
    second waits for it, then sees `applied` instead of creating a duplicate."""
    release = threading.Event()
    first_inside = threading.Event()
    real_add = actions.add_application

    def slow_add(db, data):
        application = real_add(db, data)
        if not first_inside.is_set():
            first_inside.set()
            release.wait(10)
        return application

    monkeypatch.setattr(actions, "add_application", slow_add)
    outcomes: list[object] = []

    def run() -> None:
        with Session(_engine) as s:
            try:
                outcomes.append(actions.apply(s, committed_posting, TODAY, now=NOW).id)
            except InvalidPostingStateError as exc:
                outcomes.append(exc.message)

    first = threading.Thread(target=run)
    first.start()
    assert first_inside.wait(10)
    second = threading.Thread(target=run)
    second.start()
    # Let the second Apply reach the row lock before the first commits.
    with _engine.connect() as watcher:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            waiting = watcher.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            ).scalar_one()
            watcher.rollback()
            if waiting:
                break
            time.sleep(0.02)
    release.set()
    first.join(10)
    second.join(10)

    assert not first.is_alive() and not second.is_alive()
    assert len(outcomes) == 2 and outcomes.count("already applied") == 1
    [app_id] = [o for o in outcomes if isinstance(o, int)]
    with Session(_engine) as s:
        apps = list(s.scalars(select(Application).where(Application.company == "Racecond")))
        assert [a.id for a in apps] == [app_id]
        assert s.scalar(
            select(func.count())
            .select_from(ResearchQueueItem)
            .where(ResearchQueueItem.application_id == apps[0].id)
        ) == 1
        assert s.get(Posting, committed_posting).application_id == apps[0].id


# --- paste preview -----------------------------------------------------------


def gh_job(job_id: int = 4012345, title: str = "Software Engineering Intern") -> dict:
    return {
        "id": job_id,
        "title": title,
        "company_name": "Acme Robotics",
        "location": {"name": "Boston, MA"},
        "first_published": "2026-10-01T09:00:00-04:00",
        "absolute_url": GH_JOB_URL,
    }


JSONLD_PAGE = """<html><head><title>Ignored</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "Data Science Intern",
 "hiringOrganization": {"@type": "Organization", "name": "Globex"},
 "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
   "addressLocality": "Austin", "addressRegion": "TX"}},
 "datePosted": "2026-10-02"}
</script></head><body></body></html>"""


def test_preview_of_a_board_job_link_reads_the_board_api_and_writes_nothing(db_session):
    http = FakeDiscoveryHttp({("GET", GH_JOB_API): json_result(gh_job())})

    preview = actions.paste_preview(db_session, http, f"  {GH_JOB_URL}  ")

    assert isinstance(preview, PastePreviewOut)
    assert preview.company == "Acme Robotics"
    assert preview.title == "Software Engineering Intern"
    assert preview.locations == ["Boston, MA"]
    assert preview.url == GH_JOB_URL
    assert preview.source is PostingSource.GREENHOUSE
    assert preview.date_posted == datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
    assert [(c.method, c.url) for c in http.calls] == [("GET", GH_JOB_API)]
    assert all_postings(db_session) == []
    assert not db_session.new and not db_session.dirty


def test_preview_of_another_page_reads_its_jsonld(db_session):
    url = "https://careers.globex.example/jobs/77?utm_source=x"
    http = FakeDiscoveryHttp({("PAGE", url): page_result(JSONLD_PAGE, url=url)})

    preview = actions.paste_preview(db_session, http, url)

    assert preview.company == "Globex"
    assert preview.title == "Data Science Intern"
    assert preview.locations == ["Austin, TX"]
    assert preview.source is PostingSource.PASTED
    assert preview.url == url
    assert all_postings(db_session) == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.example/a", "", "not a url"])
def test_preview_of_a_non_web_link_is_refused_without_a_request(db_session, url):
    http = FakeDiscoveryHttp()
    with pytest.raises(DiscoveryFetchError):
        actions.paste_preview(db_session, http, url)
    assert http.calls == []


def test_preview_fetch_errors_pass_through(db_session):
    url = "https://careers.globex.example/jobs/77"
    http = FakeDiscoveryHttp({("PAGE", url): DiscoveryFetchError("refused", status=None)})
    with pytest.raises(DiscoveryFetchError):
        actions.paste_preview(db_session, http, url)


@pytest.mark.parametrize(
    ("state", "message"),
    [(PostingState.SAVED, "already saved"), (PostingState.APPLIED, "already applied")],
)
def test_preview_of_a_saved_or_applied_url_is_refused_without_a_request(db_session, state, message):
    url = "https://careers.globex.example/jobs/77"
    posting = make_posting(db_session, state=PostingState.SAVED, url=url)
    if state is PostingState.APPLIED:
        actions.apply(db_session, posting.id, TODAY, now=NOW)
    http = FakeDiscoveryHttp()

    with pytest.raises(InvalidPostingStateError) as exc:
        # Same posting, different spelling: tracking params and case are ignored.
        actions.paste_preview(db_session, http, "https://CAREERS.globex.example/jobs/77/?utm_source=li")

    assert exc.value.message == message
    assert exc.value.state == state.value
    assert http.calls == []


@pytest.mark.parametrize("state", [PostingState.NEW, PostingState.DISMISSED])
def test_preview_of_a_stored_new_or_dismissed_posting_shows_the_stored_fields(db_session, state):
    # A list posting the Inbox filters hide can still be saved by pasting it.
    url = "https://careers.globex.example/jobs/77"
    make_posting(db_session, state=state, url=url, company="Globex", title="Hidden Intern")
    http = FakeDiscoveryHttp()

    preview = actions.paste_preview(db_session, http, url + "?utm_medium=x")

    assert (preview.company, preview.title, preview.url) == ("Globex", "Hidden Intern", url)
    assert preview.source is PostingSource.SIMPLIFY
    assert http.calls == []
    assert len(all_postings(db_session)) == 1


def test_preview_matches_a_stored_board_posting_by_job_id_under_another_url(db_session):
    make_posting(
        db_session,
        "4012345",
        state=PostingState.SAVED,
        source=PostingSource.GREENHOUSE,
        url="https://careers.acme.example/jobs?gh_jid=4012345",
    )
    http = FakeDiscoveryHttp()
    with pytest.raises(InvalidPostingStateError) as exc:
        actions.paste_preview(db_session, http, "https://boards.greenhouse.io/acme/jobs/4012345")
    assert exc.value.message == "already saved"
    assert http.calls == []


# --- paste confirm -----------------------------------------------------------


def confirm_in(url: str, **overrides) -> PasteConfirmIn:
    data = {
        "url": url,
        "company": "Globex",
        "title": "Data Science Intern",
        "locations": ["Austin, TX"],
        "date_posted": "2026-10-02T00:00:00Z",
    }
    data.update(overrides)
    return PasteConfirmIn.model_validate(data)


def test_confirm_saves_a_pasted_page_as_saved(db_session):
    url = "https://careers.globex.example/jobs/77?utm_source=x"
    posting = actions.paste_confirm(db_session, confirm_in(url), NOW)

    assert posting.id is not None
    assert posting.state is PostingState.SAVED
    assert posting.source is PostingSource.PASTED
    assert posting.url == url
    assert posting.url_key == "https://careers.globex.example/jobs/77"
    assert posting.source_key == posting.url_key
    assert (posting.company, posting.title, posting.locations) == (
        "Globex",
        "Data Science Intern",
        ["Austin, TX"],
    )
    assert posting.date_posted == datetime(2026, 10, 2, tzinfo=UTC)
    assert posting.terms == []
    assert posting.closed is False
    assert posting.state_changed_at == NOW
    assert posting.first_seen_at == NOW and posting.last_seen_at == NOW
    assert posting.watch_company_id is None


@pytest.mark.parametrize(
    ("url", "source", "key"),
    [
        (GH_JOB_URL, PostingSource.GREENHOUSE, "4012345"),
        (
            f"https://jobs.lever.co/acme/{LEVER_ID.upper()}/apply",
            PostingSource.LEVER,
            LEVER_ID,
        ),
        (f"https://jobs.ashbyhq.com/acme/{ASHBY_ID}", PostingSource.ASHBY, ASHBY_ID),
        (
            WORKDAY_JOB_URL,
            PostingSource.WORKDAY,
            workday_source_key(
                "nvidia.wd5.myworkdayjobs.com",
                "nvidia",
                "NVIDIAExternalCareerSite",
                "/job/US-CA-Santa-Clara/Software-Intern_JR1",
            ),
        ),
    ],
)
def test_confirm_keys_a_board_job_link_like_the_board_scan_does(db_session, url, source, key):
    posting = actions.paste_confirm(db_session, confirm_in(url), NOW)
    assert posting.source is source
    assert posting.source_key == key
    assert posting.state is PostingState.SAVED


def test_confirm_links_a_board_job_to_its_watched_company(db_session):
    company = WatchCompany(
        name="Acme",
        ats=WatchAts.GREENHOUSE,
        board_token="acme",
        careers_url="https://job-boards.greenhouse.io/acme",
    )
    db_session.add(company)
    db_session.commit()
    posting = actions.paste_confirm(db_session, confirm_in(GH_JOB_URL), NOW)
    assert posting.watch_company_id == company.id


@pytest.mark.parametrize("state", [PostingState.NEW, PostingState.DISMISSED, PostingState.SAVED])
def test_confirm_of_a_stored_url_moves_that_posting_to_saved(db_session, state):
    url = "https://careers.globex.example/jobs/77"
    existing = make_posting(db_session, state=state, url=url, closed=True, company="Old", title="Old")

    posting = actions.paste_confirm(
        db_session, confirm_in(url + "?utm_source=x", company="Globex", title="Edited"), NOW
    )

    assert posting.id == existing.id
    assert len(all_postings(db_session)) == 1
    assert posting.state is PostingState.SAVED
    assert posting.source is PostingSource.SIMPLIFY  # keeps its source and key
    assert posting.url == url
    assert posting.closed is True
    assert (posting.company, posting.title) == ("Globex", "Edited")
    expected = EARLIER if state is PostingState.SAVED else NOW
    assert posting.state_changed_at == expected


def test_confirm_of_a_stored_board_job_under_another_url_moves_it(db_session):
    existing = make_posting(
        db_session,
        "4012345",
        state=PostingState.DISMISSED,
        source=PostingSource.GREENHOUSE,
        url="https://careers.acme.example/jobs?gh_jid=4012345",
    )
    posting = actions.paste_confirm(db_session, confirm_in(GH_JOB_URL), NOW)
    assert posting.id == existing.id
    assert posting.state is PostingState.SAVED
    assert len(all_postings(db_session)) == 1


def test_confirm_of_an_applied_url_is_refused(db_session):
    url = "https://careers.globex.example/jobs/77"
    posting = make_posting(db_session, state=PostingState.SAVED, url=url)
    actions.apply(db_session, posting.id, TODAY, now=NOW)

    with pytest.raises(InvalidPostingStateError) as exc:
        actions.paste_confirm(db_session, confirm_in(url), NOW + timedelta(hours=1))

    assert exc.value.message == "already applied"
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED
    assert posting.state_changed_at == NOW


def test_confirm_of_an_applied_url_whose_application_was_deleted_saves_it_again(db_session):
    url = "https://careers.globex.example/jobs/77"
    existing = make_posting(db_session, state=PostingState.APPLIED, url=url)
    assert existing.application_id is None

    posting = actions.paste_confirm(db_session, confirm_in(url), NOW)

    assert posting.id == existing.id
    assert posting.state is PostingState.SAVED
    assert posting.state_changed_at == NOW


def test_confirm_input_is_validated_and_cleaned():
    data = confirm_in(
        "  https://careers.globex.example/jobs/77  ",
        company="  Glo\x00bex  ",
        title="Data\nScience   Intern",
        locations=["  Austin, TX ", "", "Austin, TX", "Remote"],
        date_posted="2026-10-02T00:00:00",
    )
    assert data.url == "https://careers.globex.example/jobs/77"
    assert data.company == "Glo bex"
    assert data.title == "Data Science Intern"
    assert data.locations == ["Austin, TX", "Remote"]
    assert data.date_posted == datetime(2026, 10, 2, tzinfo=UTC)
    assert confirm_in("https://x.example/1", date_posted=None).date_posted is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "javascript:alert(1)"},
        {"url": "https://x.example/" + "a" * 2000},
        {"url": "https://x.example/a b"},
        {"company": "x" * 301},
        {"company": "   "},
        {"title": "t" * 301},
        {"title": ""},
        {"locations": ["l" * 201]},
        {"locations": [f"City {i}" for i in range(21)]},
    ],
)
def test_confirm_input_rejects_bad_values(overrides):
    with pytest.raises(ValidationError):
        confirm_in(overrides.pop("url", "https://x.example/1"), **overrides)


def test_confirm_input_accepts_the_caps():
    data = confirm_in(
        "https://x.example/" + "a" * (2000 - len("https://x.example/")),
        company="c" * 300,
        title="t" * 300,
        locations=[f"{i}" + "l" * 190 for i in range(20)],
    )
    assert len(data.url) == 2000
    assert len(data.locations) == 20
