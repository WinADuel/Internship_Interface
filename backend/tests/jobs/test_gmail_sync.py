import logging
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.jobs import gmail_sync
from app.services.gmail.sync import SyncReport, google_gmail_client
from app.services.sheet_sync_service import TAB_APPLICATIONS, TAB_COMPANY, google_sheets_client


class StopLoop(Exception):
    pass


class FakeSession:
    opened: ClassVar[list["FakeSession"]] = []

    def __init__(self) -> None:
        self.closed = False
        FakeSession.opened.append(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_sessions(monkeypatch):
    FakeSession.opened = []
    monkeypatch.setattr(gmail_sync, "SessionLocal", FakeSession)
    return FakeSession.opened


class FakeSleep:
    """Records each sleep; raises StopLoop on the sleep after `stop_after`."""

    def __init__(self, stop_after: int) -> None:
        self.calls: list[float] = []
        self.stop_after = stop_after

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) > self.stop_after:
            raise StopLoop


def test_loop_waits_a_minute_then_syncs_every_configured_interval(monkeypatch, fake_sessions):
    runs = []
    minutes = iter([30, 60])
    monkeypatch.setattr(
        gmail_sync, "run_sync", lambda db, factory: runs.append((db, factory)) or SyncReport("ok")
    )
    monkeypatch.setattr(gmail_sync, "get_settings", lambda db: SimpleNamespace(gmail_sync_minutes=next(minutes)))
    factory = object()
    sleep = FakeSleep(stop_after=2)

    with pytest.raises(StopLoop):
        gmail_sync.run_forever(factory, sleep=sleep)

    assert sleep.calls == [60.0, 30 * 60.0, 60 * 60.0]
    assert len(runs) == 2 and all(f is factory for _, f in runs)
    assert runs[0][0] is not runs[1][0]
    assert len(fake_sessions) == 4 and all(s.closed for s in fake_sessions)


def test_a_crashed_run_is_retried_in_ten_minutes(monkeypatch, fake_sessions):
    runs = []

    def run(db, factory):
        runs.append(db)
        if len(runs) == 1:
            raise RuntimeError("db down")
        return SyncReport("busy")

    def broken_settings(db):
        raise RuntimeError("db down")

    monkeypatch.setattr(gmail_sync, "run_sync", run)
    monkeypatch.setattr(gmail_sync, "get_settings", broken_settings)
    sleep = FakeSleep(stop_after=2)

    with pytest.raises(StopLoop):
        gmail_sync.run_forever(object(), sleep=sleep)

    assert gmail_sync.RETRY_DELAY == 600.0
    # After the run that worked, the default interval (the settings could not be read).
    assert sleep.calls == [60.0, 600.0, 30 * 60.0]
    assert all(s.closed for s in fake_sessions)


@pytest.mark.parametrize(("stored", "expected"), [(0, 15), (5, 15), (15, 15), (240, 240)])
def test_interval_is_at_least_fifteen_minutes(monkeypatch, fake_sessions, stored, expected):
    monkeypatch.setattr(gmail_sync, "get_settings", lambda db: SimpleNamespace(gmail_sync_minutes=stored))
    assert gmail_sync.sync_interval_seconds() == expected * 60.0


def test_an_install_without_gmail_logs_nothing(monkeypatch, fake_sessions, caplog):
    monkeypatch.setattr(gmail_sync, "run_sync", lambda db, factory: SyncReport("disabled"))
    with caplog.at_level(logging.INFO, logger="app.jobs.gmail_sync"):
        gmail_sync._log(gmail_sync.run_once(object()))
        gmail_sync._log(SyncReport("not_granted"))
    assert caplog.records == []


def test_errors_and_results_are_logged(caplog):
    with caplog.at_level(logging.INFO, logger="app.jobs.gmail_sync"):
        gmail_sync._log(SyncReport("ok", listed=3, fetched=3, suggested=1, more=True, deleted=2))
        gmail_sync._log(SyncReport("error", error="gmail list rejected (status 500)"))
        gmail_sync._log(SyncReport("busy"))
    messages = [r.getMessage() for r in caplog.records]
    assert messages == [
        "gmail sync done: 3 new, 3 fetched, 1 suggestion(s), 0 auto-applied; more next run",
        "gmail retention: deleted 2 old suggestion(s)",
        "gmail sync failed: gmail list rejected (status 500)",
        "gmail sync skipped: another sync is running",
    ]


def test_main_sets_up_logging_and_uses_the_real_client(monkeypatch):
    seen = []
    monkeypatch.setattr(gmail_sync, "configure_job_logging", lambda: seen.append("logging"))
    monkeypatch.setattr(gmail_sync, "run_forever", lambda: seen.append("loop"))
    gmail_sync.main()
    assert seen == ["logging", "loop"]
    assert gmail_sync.run_once.__defaults__ == (google_gmail_client, google_sheets_client)


def test_auto_applied_changes_reach_the_backup_sheet(monkeypatch, fake_sessions):
    synced = []
    report = SyncReport("ok", auto_applied=2, sheet_tabs={TAB_COMPANY, TAB_APPLICATIONS})
    monkeypatch.setattr(gmail_sync, "run_sync", lambda db, factory: report)
    monkeypatch.setattr(gmail_sync, "safe_sync", lambda db, factory, tabs: synced.append((db, factory, tabs)))
    sheets = object()

    assert gmail_sync.run_once(object(), sheets) is report

    ((db, factory, tabs),) = synced
    assert db is fake_sessions[0] and factory is sheets
    assert tabs == [TAB_APPLICATIONS, TAB_COMPANY]  # in the sheet's tab order
    assert fake_sessions[0].closed


def test_no_sheet_sync_without_auto_applied_changes(monkeypatch, fake_sessions):
    monkeypatch.setattr(gmail_sync, "run_sync", lambda db, factory: SyncReport("ok", suggested=3))
    monkeypatch.setattr(gmail_sync, "safe_sync", lambda *a: pytest.fail("no sheet sync expected"))
    gmail_sync.run_once(object(), object())
