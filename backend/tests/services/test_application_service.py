from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import ApplicationStatus
from app.models.interview import InterviewState
from app.schemas.application import ApplicationCreate
from app.services.application_service import (
    archive_application,
    change_status,
    create_application,
    get_application,
    get_recent_activity,
    get_status_history,
    list_applications,
    update_application,
)
from app.schemas.application import ApplicationUpdate
from app.services.errors import ApplicationNotFoundError
from app.services.interview_service import DEFAULT_CHECKLIST, list_rounds


def test_create_and_get_application(db_session):
    app = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE Intern"))
    fetched = get_application(db_session, app.id)
    assert fetched.company == "Stripe"


def test_get_application_raises_when_missing(db_session):
    with pytest.raises(ApplicationNotFoundError):
        get_application(db_session, 999)


def test_list_applications_excludes_archived_by_default(db_session):
    active = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    archived = create_application(db_session, ApplicationCreate(company="B", role_title="R"))
    archive_application(db_session, archived.id)
    results = list_applications(db_session)
    assert [a.id for a in results] == [active.id]
    assert len(list_applications(db_session, include_archived=True)) == 2


def test_change_status_writes_history_row(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    history = get_status_history(db_session, app.id)
    assert len(history) == 2
    assert history[-1].old_status == ApplicationStatus.WISHLIST
    assert history[-1].new_status == ApplicationStatus.APPLIED


def test_create_application_writes_initial_history_row(db_session):
    app = create_application(
        db_session,
        ApplicationCreate(company="A", role_title="R", status=ApplicationStatus.APPLIED),
    )
    history = get_status_history(db_session, app.id)
    assert len(history) == 1
    assert history[0].old_status is None
    assert history[0].new_status == ApplicationStatus.APPLIED


def test_change_status_to_same_status_is_a_noop(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.WISHLIST)  # already wishlist
    history = get_status_history(db_session, app.id)
    assert len(history) == 1  # only the creation row
    assert history[0].old_status is None
    assert history[0].new_status == ApplicationStatus.WISHLIST


def test_get_recent_activity_orders_newest_first(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    change_status(db_session, app.id, ApplicationStatus.PHONE_SCREEN)
    activity = get_recent_activity(db_session, limit=10)
    assert [a["new_status"] for a in activity[:2]] == [ApplicationStatus.PHONE_SCREEN, ApplicationStatus.APPLIED]


def test_create_with_future_interview_datetime_makes_a_scheduled_round(db_session):
    when = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=3)
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R", interview_datetime=when))
    (interview_round,) = list_rounds(db_session, application_id=app.id)
    assert interview_round.scheduled_at == when
    assert interview_round.state == InterviewState.SCHEDULED
    assert [item["label"] for item in interview_round.checklist] == list(DEFAULT_CHECKLIST)
    assert app.interview_datetime == when


def test_create_with_past_naive_interview_datetime_makes_a_done_round(db_session):
    when = datetime(2026, 3, 5, 14, 30)  # naive: taken as UTC
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R", interview_datetime=when))
    (interview_round,) = list_rounds(db_session, application_id=app.id)
    assert interview_round.scheduled_at == when.replace(tzinfo=timezone.utc)
    assert interview_round.state == InterviewState.DONE
    assert app.interview_datetime is None  # derived: no round is still scheduled


def test_create_without_interview_datetime_makes_no_round(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    assert list_rounds(db_session, application_id=app.id) == []


def test_update_ignores_interview_datetime(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    data = ApplicationUpdate.model_validate({"notes": "n", "interview_datetime": "2027-01-01T10:00:00Z"})
    assert "interview_datetime" not in data.model_dump()
    update_application(db_session, app.id, data)
    assert app.notes == "n"
    assert app.interview_datetime is None
    assert list_rounds(db_session, application_id=app.id) == []
