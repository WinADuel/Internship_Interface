from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.jobs import job_scan
from app.services.discovery.http import HttpxDiscoveryHttp
from app.services.discovery.scanner import ScanReport


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
    monkeypatch.setattr(job_scan, "SessionLocal", FakeSession)
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


@pytest.fixture(autouse=True)
def rescore_checks(monkeypatch):
    """Stands in for the daily re-score check; records the session of each."""
    checks: list[object] = []
    monkeypatch.setattr(job_scan, "rescore_if_due", lambda db: checks.append(db) or False)
    return checks


HOUR = 3600.0


def test_loop_waits_a_minute_then_scans_and_sleeps_the_configured_hours_each_time(
    monkeypatch, fake_sessions, rescore_checks
):
    scans = []
    hours = iter([2, 3])
    monkeypatch.setattr(
        job_scan,
        "run_scan",
        lambda db, http: scans.append((db, http)) or ScanReport(1, 0, 0, []),
    )
    monkeypatch.setattr(
        job_scan, "get_settings", lambda db: SimpleNamespace(discovery_scan_hours=next(hours))
    )
    http = object()
    sleep = FakeSleep(stop_after=5)

    with pytest.raises(StopLoop):
        job_scan.run_forever(http, sleep=sleep)

    # Startup delay, then two scans, each followed by the interval re-read
    # from settings (2 h, then 3 h), slept an hour at a time.
    assert sleep.calls == [60.0] + [HOUR] * 5
    assert len(scans) == 2
    assert all(h is http for _, h in scans)
    # Every session opened (for the scans, the intervals and the re-score
    # checks) is closed.
    assert len(fake_sessions) == 2 + 2 + len(rescore_checks)
    assert all(s.closed for s in fake_sessions)
    assert scans[0][0] is not scans[1][0]


def test_the_daily_rescore_is_checked_at_startup_and_after_every_hour_of_waiting(monkeypatch, fake_sessions):
    events: list[str] = []
    monkeypatch.setattr(job_scan, "run_scan", lambda db, http: events.append("scan") or ScanReport())
    monkeypatch.setattr(job_scan, "get_settings", lambda db: SimpleNamespace(discovery_scan_hours=48))
    monkeypatch.setattr(job_scan, "rescore_if_due", lambda db: events.append("check") or False)
    sleep = FakeSleep(stop_after=49)

    def recording_sleep(seconds: float) -> None:
        events.append(f"sleep {seconds:.0f}")
        sleep(seconds)

    with pytest.raises(StopLoop):
        job_scan.run_forever(object(), sleep=recording_sleep)

    # Even with the longest interval (48 h) the check runs every hour, so the
    # freshness points are refreshed once they are 20 h old, not 48.
    assert events[:4] == ["sleep 60", "check", "scan", "sleep 3600"]
    assert events[4:100] == ["check", "sleep 3600"] * 47 + ["check", "scan"]


def test_a_failing_rescore_check_is_logged_and_the_loop_goes_on(monkeypatch, fake_sessions, caplog):
    scans = []
    monkeypatch.setattr(job_scan, "run_scan", lambda db, http: scans.append(db) or ScanReport())
    monkeypatch.setattr(job_scan, "get_settings", lambda db: SimpleNamespace(discovery_scan_hours=1))

    def broken(db):
        raise RuntimeError("db down")

    monkeypatch.setattr(job_scan, "rescore_if_due", broken)
    sleep = FakeSleep(stop_after=2)

    with pytest.raises(StopLoop):
        job_scan.run_forever(object(), sleep=sleep)

    assert len(scans) == 2
    assert "daily re-score failed" in caplog.text
    assert all(s.closed for s in fake_sessions)


def test_a_rescore_that_ran_is_logged(monkeypatch, fake_sessions, caplog):
    monkeypatch.setattr(job_scan, "rescore_if_due", lambda db: True)
    with caplog.at_level("INFO", logger=job_scan.__name__):
        job_scan.check_rescore()
    assert "daily re-score done" in caplog.text


def test_loop_survives_a_crashing_scan_and_a_failed_settings_read(monkeypatch, fake_sessions):
    scans = []

    def crashing_scan(db, http):
        scans.append(db)
        if len(scans) == 1:
            raise RuntimeError("db down")
        return None  # another scan held the lock

    def broken_settings(db):
        raise RuntimeError("db down")

    monkeypatch.setattr(job_scan, "run_scan", crashing_scan)
    monkeypatch.setattr(job_scan, "get_settings", broken_settings)
    sleep = FakeSleep(stop_after=8)

    with pytest.raises(StopLoop):
        job_scan.run_forever(object(), sleep=sleep)

    assert len(scans) == 3
    # A crashed scan is retried in ten minutes (the database may be briefly
    # down); after the scan that worked, the normal interval applies — here
    # the default, since the settings could not be read either.
    assert sleep.calls[:8] == [60.0, job_scan.RETRY_DELAY] + [HOUR] * 6
    assert all(s.closed for s in fake_sessions)


def test_a_crashed_scan_is_retried_sooner_than_the_configured_interval(
    monkeypatch, fake_sessions
):
    scans = []
    settings_reads = []

    def scan(db, http):
        scans.append(db)
        if len(scans) == 1:
            raise RuntimeError("db down")
        return ScanReport(1, 0, 0, [])

    monkeypatch.setattr(job_scan, "run_scan", scan)
    monkeypatch.setattr(
        job_scan,
        "get_settings",
        lambda db: settings_reads.append(db) or SimpleNamespace(discovery_scan_hours=12),
    )
    sleep = FakeSleep(stop_after=13)

    with pytest.raises(StopLoop):
        job_scan.run_forever(object(), sleep=sleep)

    assert job_scan.RETRY_DELAY == 600.0
    assert sleep.calls[:14] == [60.0, 600.0] + [HOUR] * 12
    # The settings are not even read after a crash: the database may be down.
    assert len(settings_reads) == 1


@pytest.mark.parametrize(("stored", "expected"), [(0, 1), (-5, 1), (1, 1), (48, 48)])
def test_interval_is_at_least_one_hour(monkeypatch, fake_sessions, stored, expected):
    monkeypatch.setattr(
        job_scan, "get_settings", lambda db: SimpleNamespace(discovery_scan_hours=stored)
    )
    assert job_scan.scan_interval_seconds() == expected * 3600.0


def test_main_sets_up_logging_and_uses_the_real_http_client(monkeypatch):
    seen = []
    monkeypatch.setattr(job_scan, "configure_job_logging", lambda: seen.append("logging"))
    monkeypatch.setattr(job_scan, "run_forever", lambda http: seen.append(http))
    job_scan.main()
    assert len(seen) == 2 and seen[0] == "logging" and isinstance(seen[1], HttpxDiscoveryHttp)
