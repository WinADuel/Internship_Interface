import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

load_dotenv()  # populates os.environ from backend/.env for local dev/test runs

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def _engine():
    """Session-scoped engine for the test database; creates all tables once."""
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(_engine):
    """Function-scoped session wrapping a transaction that is always rolled
    back, so each test sees a clean database regardless of what it writes.

    The session is bound to a SAVEPOINT (`connection.begin_nested()`), not
    directly to the outer transaction. If code under test calls
    `session.commit()` (the normal pattern in services), SQLAlchemy only
    ends that SAVEPOINT — the outer transaction is untouched. The
    `after_transaction_end` listener immediately opens a fresh SAVEPOINT so
    later writes in the same test are still captured. Only `transaction`
    (the outer one) is ever rolled back here, so a commit from application
    code can never leak data past this fixture's teardown. See:
    https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
    """
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    event.remove(session, "after_transaction_end", _restart_savepoint)
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """TestClient with the `get_db` dependency overridden to use the
    per-test transactional session, so API calls in tests share its rollback."""

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
