from datetime import datetime

from app.jobs import nightly_sheet_sync
from app.jobs.nightly_sheet_sync import seconds_until_next_run


def test_seconds_until_next_run():
    assert seconds_until_next_run(datetime(2026, 10, 6, 2, 0)) == 3600
    assert seconds_until_next_run(datetime(2026, 10, 6, 3, 0)) == 86400
    assert seconds_until_next_run(datetime(2026, 10, 6, 23, 30)) == 3.5 * 3600


def test_run_once_uses_a_fresh_session_and_closes_it(monkeypatch):
    calls = []

    class FakeSession:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(nightly_sheet_sync, "SessionLocal", FakeSession)
    monkeypatch.setattr(nightly_sheet_sync, "safe_sync", lambda db, factory, tabs: calls.append(tuple(tabs)) or True)
    assert nightly_sheet_sync.run_once() is True
    assert calls == [("Applications", "Professors", "Company Contacts"), "closed"]
