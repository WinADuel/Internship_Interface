import logging
from datetime import datetime
from pathlib import Path

import pytest

from app.jobs import db_backup
from app.jobs.db_backup import seconds_until_next_run
from app.services.backup.service import BackupResult


def test_seconds_until_next_run_is_0230_local():
    assert seconds_until_next_run(datetime(2026, 10, 6, 2, 0)) == 1800
    assert seconds_until_next_run(datetime(2026, 10, 6, 2, 30)) == 86400
    assert seconds_until_next_run(datetime(2026, 10, 6, 2, 30, 1)) == 86399
    assert seconds_until_next_run(datetime(2026, 10, 6, 23, 30)) == 3 * 3600


class FakeSession:
    def __init__(self, log):
        self.log = log

    def close(self):
        self.log.append("closed")


@pytest.fixture()
def job(monkeypatch, tmp_path):
    """run_once with a fake session and a recording run_backup."""
    log = []
    outcomes = []

    def fake_run_backup(db, label, *, database_url, backup_dir, after=None):
        log.append(("run_backup", label, database_url, backup_dir, after))
        return outcomes.pop(0) if outcomes else BackupResult(label=label, path=Path("x"), status_recorded=True)

    monkeypatch.setattr(db_backup, "SessionLocal", lambda: FakeSession(log))
    monkeypatch.setattr(db_backup, "run_backup", fake_run_backup)
    monkeypatch.setattr(db_backup.settings, "backup_dir", str(tmp_path))
    return log, outcomes


def test_run_once_uses_settings_and_a_fresh_session(job, tmp_path):
    log, _ = job
    assert db_backup.run_once("pre-deploy").ok
    assert log == [("run_backup", "pre-deploy", db_backup.settings.database_url, str(tmp_path), None), "closed"]


def test_run_once_passes_the_after_step_for_its_label(job, monkeypatch):
    log, _ = job
    step = lambda db, path: None  # noqa: E731
    monkeypatch.setitem(db_backup.AFTER_BACKUP, "nightly", step)
    db_backup.run_once("nightly")
    db_backup.run_once("pre-deploy")
    assert log[0][4] is step
    assert log[2][4] is None


def test_once_exit_codes(job):
    _, outcomes = job
    outcomes.append(BackupResult(label="pre-deploy", path=Path("x"), status_recorded=True))
    assert db_backup.main(["--once", "--label", "pre-deploy"]) == 0
    outcomes.append(BackupResult(label="pre-deploy", error="pg_dump failed", status_recorded=True))
    assert db_backup.main(["--once", "--label", "pre-deploy"]) == 1


def test_once_defaults_to_the_manual_label(job):
    log, _ = job
    assert db_backup.main(["--once"]) == 0
    assert log[0][1] == "manual"


def test_once_succeeds_when_only_the_status_could_not_be_saved(job, caplog):
    _, outcomes = job
    outcomes.append(BackupResult(label="pre-deploy", path=Path("x"), status_recorded=False))
    with caplog.at_level(logging.WARNING):
        assert db_backup.main(["--once", "--label", "pre-deploy"]) == 0
    assert "pre-deploy backup succeeded, but Settings could not be updated" in caplog.text


def test_once_crash_exits_1(monkeypatch):
    def boom():
        raise RuntimeError("no database")

    monkeypatch.setattr(db_backup, "SessionLocal", boom)
    assert db_backup.main(["--once", "--label", "manual"]) == 1


def test_bad_label_is_a_usage_error(job):
    with pytest.raises(SystemExit) as excinfo:
        db_backup.main(["--once", "--label", "weekly"])
    assert excinfo.value.code == 2


def test_label_without_once_is_a_usage_error(job):
    with pytest.raises(SystemExit) as excinfo:
        db_backup.main(["--label", "manual"])
    assert excinfo.value.code == 2


class _Stop(Exception):
    pass


def test_loop_waits_for_0230_runs_nightly_and_survives_crashes(monkeypatch, caplog):
    sleeps = []
    runs = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 3:
            raise _Stop

    def run_once(label):
        runs.append(label)
        if len(runs) == 1:
            raise RuntimeError("database restarting")
        return BackupResult(label=label, error="pg_dump failed" if len(runs) == 2 else None)

    monkeypatch.setattr(db_backup, "run_once", run_once)
    with caplog.at_level(logging.INFO), pytest.raises(_Stop):
        db_backup.run_forever(sleep=sleep, now=lambda: datetime(2026, 10, 6, 1, 30))
    assert sleeps == [3600.0] * 4
    assert runs == ["nightly"] * 3
    assert "nightly backup crashed" in caplog.text
    assert "nightly backup failed (see Settings)" in caplog.text
    assert "nightly backup succeeded" in caplog.text


def test_default_runs_the_loop(monkeypatch):
    called = []
    monkeypatch.setattr(db_backup, "run_forever", lambda: called.append(True))
    db_backup.main([])
    assert called == [True]
