import pytest

from app.models.application import ApplicationStatus
from app.schemas.application import ApplicationCreate
from app.services.application_service import (
    archive_application,
    change_status,
    create_application,
    get_application,
    get_recent_activity,
    get_status_history,
    list_applications,
)
from app.services.errors import ApplicationNotFoundError


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
