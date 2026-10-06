import pytest
from sqlalchemy.exc import IntegrityError

from app.models.application import Application, ApplicationStatus, Priority
from app.models.oauth_token import OAuthToken
from app.models.status_history import StatusHistory


def test_create_application_defaults(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    assert app.status == ApplicationStatus.WISHLIST
    assert app.priority == Priority.MEDIUM
    assert app.archived is False


def test_application_timestamps_set_and_nullable_fields_empty(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    db_session.refresh(app)
    assert app.created_at is not None
    assert app.updated_at is not None
    assert app.job_link is None
    assert app.follow_up_date is None
    assert app.interview_datetime is None


def test_application_requires_company(db_session):
    db_session.add(Application(role_title="SWE Intern"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_status_enum_persists_value_and_roundtrips(db_session):
    app = Application(company="Stripe", role_title="SWE Intern", status=ApplicationStatus.PHONE_SCREEN)
    db_session.add(app)
    db_session.flush()
    raw = db_session.connection().exec_driver_sql(
        "SELECT status::text FROM applications WHERE id = %s", (app.id,)
    ).scalar_one()
    assert raw == "phone_screen"
    db_session.expire(app)
    assert app.status == ApplicationStatus.PHONE_SCREEN


def test_status_history_links_to_application(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    history = StatusHistory(application_id=app.id, old_status=None, new_status=ApplicationStatus.WISHLIST)
    db_session.add(history)
    db_session.flush()
    assert history.application_id == app.id
    db_session.refresh(history)
    assert history.old_status is None
    assert history.changed_at is not None


def test_status_history_rejects_unknown_application(db_session):
    db_session.add(StatusHistory(application_id=999999, new_status=ApplicationStatus.APPLIED))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_oauth_token_stores_bytes(db_session):
    token = OAuthToken(provider="google", encrypted_refresh_token=b"\x00cipher", scopes="drive.file")
    db_session.add(token)
    db_session.flush()
    db_session.refresh(token)
    assert bytes(token.encrypted_refresh_token) == b"\x00cipher"
    assert token.created_at is not None and token.updated_at is not None
