import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.jobs import nightly_sheet_sync


class _Stop(Exception):
    pass


def test_loop_runs_at_0300_local_each_day_and_survives_crashes(monkeypatch, caplog):
    # TZ is read by app/jobs/schedule (tests/jobs/test_schedule.py covers DST days).
    monkeypatch.setenv("TZ", "Europe/London")
    clock = [datetime(2026, 10, 24, 1, 0, tzinfo=UTC)]  # 02:00 BST; London falls back on the 25th
    sleeps = []
    runs = []

    def sleep(seconds):
        if len(runs) == 3:
            raise _Stop  # (the loop catches anything run_once raises)
        sleeps.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    def run_once():
        runs.append(clock[0])
        clock[0] += timedelta(minutes=5)
        if len(runs) == 1:
            raise RuntimeError("database restarting")
        return True

    monkeypatch.setattr(nightly_sheet_sync, "run_once", run_once)
    with caplog.at_level(logging.INFO), pytest.raises(_Stop):
        nightly_sheet_sync.run_forever(sleep=sleep, now=lambda: clock[0])
    # 03:00 BST, then 03:00 GMT (a 25-hour day), then 03:00 GMT.
    assert runs == [
        datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 3, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 3, 0, tzinfo=UTC),
    ]
    assert sleeps == [3600.0, 25 * 3600.0 - 300, 24 * 3600.0 - 300]
    assert "nightly sheet sync crashed" in caplog.text
    assert "nightly sheet sync succeeded" in caplog.text


def test_main_sets_up_logging_and_runs_the_loop(monkeypatch):
    called = []
    monkeypatch.setattr(nightly_sheet_sync, "configure_job_logging", lambda: called.append("logging"))
    monkeypatch.setattr(nightly_sheet_sync, "run_forever", lambda: called.append("loop"))
    nightly_sheet_sync.main()
    assert called == ["logging", "loop"]


def test_run_once_uses_a_fresh_session_and_closes_it(monkeypatch):
    calls = []

    class FakeSession:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(nightly_sheet_sync, "SessionLocal", FakeSession)
    monkeypatch.setattr(nightly_sheet_sync, "safe_sync", lambda db, factory, tabs: calls.append(tuple(tabs)) or True)
    assert nightly_sheet_sync.run_once() is True
    assert calls == [("Applications", "Professors", "Company Contacts", "Saved postings"), "closed"]
