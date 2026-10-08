import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

load_dotenv()  # populates os.environ from backend/.env for local dev/test runs

from app.db.base import Base  # noqa: E402
from app.api.deps import get_sheet_sync_scheduler  # noqa: E402
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


class RecordingSheetSyncScheduler:
    """Stands in for the real scheduler, which would open its own DB session
    and call Google; records the tabs each write asked to re-sync."""

    def __init__(self) -> None:
        self.scheduled: list[list[str]] = []

    def schedule(self, background_tasks, tabs) -> None:
        self.scheduled.append(list(tabs))


@pytest.fixture()
def sheet_sync_recorder():
    return RecordingSheetSyncScheduler()


@pytest.fixture()
def client(db_session, sheet_sync_recorder):
    """TestClient with the `get_db` dependency overridden to use the
    per-test transactional session, so API calls in tests share its rollback.
    Sheet sync is replaced by a recorder (see test_sheet_sync_hooks.py)."""

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_sheet_sync_scheduler] = lambda: sheet_sync_recorder
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_sheet_sync_scheduler, None)


class FakeClock:
    """Deterministic stand-in for the login throttle's monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def login_throttle_clock(monkeypatch):
    """Reset the in-process login throttle around every test and drive it with
    a fake clock, so lockout state never leaks between tests."""
    from app.services.auth_service import login_throttle

    clock = FakeClock()
    monkeypatch.setattr(login_throttle, "clock", clock)
    login_throttle.reset()
    yield clock
    login_throttle.reset()
