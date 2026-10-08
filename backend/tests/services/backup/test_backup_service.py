import logging
from datetime import datetime, timezone
from pathlib import Path

from app.services import settings_service
from app.services.backup import service
from app.services.backup.dump import BackupError
from app.services.backup.service import run_backup

NOW = datetime(2026, 10, 8, 7, 30, tzinfo=timezone.utc)
EARLIER = datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc)
URL = "postgresql+psycopg://app:pw@db/tracker"


def _run(db, label, backup_dir, dump, **kwargs):
    return run_backup(db, label, database_url=URL, backup_dir=backup_dir, now=NOW, dump=dump, **kwargs)


def _ok_dump(calls):
    def dump(database_url, backup_dir, label, now):
        calls.append((database_url, backup_dir, label, now))
        path = Path(backup_dir) / label / "tracker-20261008T073000Z.dump"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    return dump


def _failing_dump(message):
    def dump(database_url, backup_dir, label, now):
        raise BackupError(message)

    return dump


def test_success_records_time_and_clears_the_error(db_session, tmp_path):
    settings_service.get_settings(db_session).last_backup_error = "old failure"
    db_session.commit()
    calls = []
    result = _run(db_session, "nightly", tmp_path, _ok_dump(calls))
    assert result.ok and result.status_recorded
    assert result.path == tmp_path / "nightly" / "tracker-20261008T073000Z.dump"
    assert calls == [(URL, tmp_path, "nightly", NOW)]
    s = settings_service.get_settings(db_session)
    assert s.last_backup_at == NOW
    assert s.last_backup_error is None


def test_failure_records_the_error_and_keeps_the_last_success(db_session, tmp_path):
    s = settings_service.get_settings(db_session)
    s.last_backup_at = EARLIER
    db_session.commit()
    result = _run(db_session, "nightly", tmp_path, _failing_dump("pg_dump failed (exit 1): boom"))
    assert not result.ok and result.status_recorded
    assert result.error == "pg_dump failed (exit 1): boom"
    s = settings_service.get_settings(db_session)
    assert s.last_backup_at == EARLIER
    assert s.last_backup_error == "pg_dump failed (exit 1): boom"


def test_unexpected_crash_becomes_a_generic_error(db_session, tmp_path):
    def dump(*args):
        raise RuntimeError("secret detail")

    result = _run(db_session, "manual", tmp_path, dump)
    assert result.error == "backup failed unexpectedly (RuntimeError)"
    assert settings_service.get_settings(db_session).last_backup_error == result.error


def test_success_applies_retention(db_session, tmp_path):
    folder = tmp_path / "manual"
    folder.mkdir()
    old = [folder / f"tracker-2026100{d}T000000Z.dump" for d in range(1, 7)]
    for p in old:
        p.write_bytes(b"x")
    result = _run(db_session, "manual", tmp_path, _ok_dump([]))
    assert result.deleted == old[:2]
    assert result.path.exists()


def test_failure_does_not_prune(db_session, tmp_path):
    folder = tmp_path / "manual"
    folder.mkdir()
    old = [folder / f"tracker-2026100{d}T000000Z.dump" for d in range(1, 8)]
    for p in old:
        p.write_bytes(b"x")
    _run(db_session, "manual", tmp_path, _failing_dump("x"))
    assert all(p.exists() for p in old)


def test_retention_failure_does_not_fail_the_backup(db_session, tmp_path, monkeypatch, caplog):
    def broken_prune(backup_dir, label):
        raise OSError("disk trouble")

    monkeypatch.setattr(service, "prune", broken_prune)
    with caplog.at_level(logging.ERROR):
        result = _run(db_session, "manual", tmp_path, _ok_dump([]))
    assert result.ok and result.status_recorded
    assert "retention failed" in caplog.text


class _DownSession:
    """A session whose database is unreachable."""

    def __init__(self):
        self.rolled_back = False

    def get(self, *args, **kwargs):
        raise ConnectionError("database is down")

    def rollback(self):
        self.rolled_back = True


def test_status_failure_does_not_hide_a_good_dump(tmp_path, caplog):
    db = _DownSession()
    with caplog.at_level(logging.ERROR):
        result = _run(db, "pre-deploy", tmp_path, _ok_dump([]))
    assert result.ok
    assert result.path.exists()
    assert result.status_recorded is False
    assert db.rolled_back
    assert "could not record the backup outcome" in caplog.text


def test_status_failure_keeps_a_failed_dump_failed(tmp_path):
    result = _run(_DownSession(), "pre-deploy", tmp_path, _failing_dump("boom"))
    assert not result.ok and result.status_recorded is False


def test_after_step_runs_only_on_success_with_the_dump(db_session, tmp_path):
    seen = []
    after = lambda db, path: seen.append((db, path))  # noqa: E731
    ok = _run(db_session, "nightly", tmp_path, _ok_dump([]), after=after)
    _run(db_session, "nightly", tmp_path, _failing_dump("x"), after=after)
    assert seen == [(db_session, ok.path)]


def test_after_step_failure_does_not_fail_the_local_backup(db_session, tmp_path, caplog):
    def after(db, path):
        raise RuntimeError("drive down")

    with caplog.at_level(logging.ERROR):
        result = _run(db_session, "nightly", tmp_path, _ok_dump([]), after=after)
    assert result.ok
    assert settings_service.get_settings(db_session).last_backup_error is None
    assert "step after the nightly backup failed" in caplog.text
