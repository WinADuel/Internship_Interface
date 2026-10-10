from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.api.deps import get_backup_dump
from app.core.config import settings as app_config
from app.main import app
from app.services import settings_service
from app.services.backup.dump import BackupError
from app.services.backup.lock import BACKUP_LOCK_KEY
from app.services.google_docs_service import store_token

ROUTES = [
    ("GET", "/api/backups/status"),
    ("POST", "/api/backups/run"),
]
EARLIER = datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc)


def test_routes_list_is_complete():
    # The auth and Claude-token boundary tests walk ROUTES; keep it complete.
    from app.api.backups import router

    served = {(method, route.path) for route in router.routes for method in route.methods - {"HEAD", "OPTIONS"}}
    assert served == set(ROUTES)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_a_session(client, method, path):
    assert client.request(method, path).status_code == 401


class FakeDump:
    def __init__(self, error: str | None = None):
        self.calls = []
        self.error = error

    def __call__(self, database_url, backup_dir, label, now):
        self.calls.append((database_url, str(backup_dir), label))
        if self.error:
            raise BackupError(self.error)
        path = Path(backup_dir) / label / "tracker-20261008T073000Z.dump"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PGDMP")
        return path


@pytest.fixture()
def fake_dump(monkeypatch, tmp_path):
    fake = FakeDump()
    monkeypatch.setattr(app_config, "backup_dir", str(tmp_path))
    app.dependency_overrides[get_backup_dump] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_backup_dump, None)


@pytest.fixture()
def other_connection(_engine):
    """Another backup (the nightly job, say), holding the lock elsewhere."""
    conn = _engine.connect()
    yield conn
    conn.execute(text("SELECT pg_advisory_unlock_all()"))
    conn.rollback()
    conn.close()


def _try_lock(conn) -> bool:
    return conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": BACKUP_LOCK_KEY}).scalar_one()


def test_status_when_nothing_has_run(logged_in_client, monkeypatch):
    monkeypatch.setattr(app_config, "backup_encryption_key", None)
    r = logged_in_client.get("/api/backups/status")
    assert r.status_code == 200
    assert r.json() == {
        "last_backup_at": None,
        "last_backup_error": None,
        "last_offsite_at": None,
        "last_offsite_error": None,
        "offsite_configured": False,
    }


def test_status_reports_times_errors_and_configuration(logged_in_client, db_session, monkeypatch):
    row = settings_service.get_settings(db_session)
    row.last_backup_at = EARLIER
    row.last_offsite_error = "connect Google in Settings"
    db_session.commit()
    monkeypatch.setattr(app_config, "backup_encryption_key", Fernet.generate_key().decode())
    store_token(db_session, {"refresh_token": "refresh"}, scopes="drive.file")
    body = logged_in_client.get("/api/backups/status").json()
    assert datetime.fromisoformat(body["last_backup_at"]) == EARLIER
    assert body["last_offsite_error"] == "connect Google in Settings"
    assert body["offsite_configured"] is True


def test_back_up_now_takes_a_local_manual_backup(logged_in_client, db_session, fake_dump, tmp_path):
    row = settings_service.get_settings(db_session)
    row.last_backup_error = "old failure"
    row.last_offsite_at = EARLIER
    db_session.commit()
    r = logged_in_client.post("/api/backups/run")
    assert r.status_code == 200
    body = r.json()
    assert body["last_backup_at"] is not None and body["last_backup_error"] is None
    # Manual dumps stay local: the off-site status is untouched.
    assert datetime.fromisoformat(body["last_offsite_at"]) == EARLIER
    assert body["last_offsite_error"] is None
    assert fake_dump.calls == [(app_config.database_url, str(tmp_path), "manual")]
    assert (tmp_path / "manual" / "tracker-20261008T073000Z.dump").exists()


def test_back_up_now_reports_a_failed_dump(logged_in_client, fake_dump):
    fake_dump.error = "pg_dump failed (exit 1): connection refused"
    r = logged_in_client.post("/api/backups/run")
    assert r.status_code == 200
    assert r.json()["last_backup_error"] == "pg_dump failed (exit 1): connection refused"


def test_back_up_now_is_409_while_another_backup_runs(logged_in_client, fake_dump, other_connection):
    assert _try_lock(other_connection)
    r = logged_in_client.post("/api/backups/run")
    assert r.status_code == 409
    assert r.json() == {"detail": "a backup is already running"}
    assert fake_dump.calls == []


def test_back_up_now_releases_the_lock(logged_in_client, fake_dump, other_connection):
    held_during = []
    real = fake_dump.__call__

    def dump(*args):
        held_during.append(_try_lock(other_connection))
        return real(*args)

    app.dependency_overrides[get_backup_dump] = lambda: dump
    assert logged_in_client.post("/api/backups/run").status_code == 200
    assert held_during == [False]
    assert _try_lock(other_connection)  # free again afterwards
