import inspect
import logging
import stat
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings as app_config
from app.services import settings_service
from app.services.backup import offsite
from app.services.backup.crypto import decrypt_bytes
from app.services.backup.drive_client import FOLDER_NAME, DriveError, DriveFile
from app.services.backup.offsite import (
    KEEP_OFFSITE,
    NO_KEY,
    NOT_CONNECTED,
    backup_status,
    google_drive_client,
    offsite_copy,
    prune_offsite,
)
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import store_token

KEY = Fernet.generate_key().decode()
NOW = datetime(2026, 10, 8, 7, 31, tzinfo=timezone.utc)
EARLIER = datetime(2026, 10, 7, 7, 31, tzinfo=timezone.utc)
DUMP_NAME = "tracker-20261008T073000Z.dump"


def _copy_name(day: int) -> str:
    return f"tracker-202609{day:02d}T073000Z.dump.enc"


class FakeDrive:
    """Stands in for GoogleDriveClient; files are kept newest first."""

    def __init__(self, files=None):
        self.folders: list[str] = []
        self.files: list[DriveFile] = list(files or [])
        self.uploads: list[tuple[str, str, bytes, int]] = []
        self.deleted: list[str] = []
        self.fail_on: dict[str, Exception] = {}

    def _maybe_fail(self, op):
        if op in self.fail_on:
            raise self.fail_on[op]

    def find_or_create_folder(self, name):
        self._maybe_fail("folder")
        self.folders.append(name)
        return "folder1"

    def upload(self, folder_id, name, path):
        self._maybe_fail("upload")
        self.uploads.append((folder_id, name, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
        new = DriveFile(f"new{len(self.uploads)}", name)
        self.files.insert(0, new)
        return new.id

    def list_files(self, folder_id):
        self._maybe_fail("list")
        return list(self.files)

    def delete(self, file_id):
        self._maybe_fail("delete")
        self.deleted.append(file_id)


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setattr(app_config, "backup_encryption_key", KEY)
    return KEY


@pytest.fixture()
def connected(db_session):
    store_token(db_session, {"refresh_token": "refresh"}, scopes="drive.file")


@pytest.fixture()
def dump(tmp_path):
    path = tmp_path / "nightly" / DUMP_NAME
    path.parent.mkdir()
    path.write_bytes(b"PGDMP the whole database")
    return path


def _factory(drive, calls=None):
    def factory(db):
        if calls is not None:
            calls.append(db)
        return drive

    return factory


def _row(db):
    return settings_service.get_settings(db)


def test_uploads_an_encrypted_copy_and_records_success(db_session, key, connected, dump):
    row = _row(db_session)
    row.last_offsite_error = "old failure"
    db_session.commit()
    drive = FakeDrive()
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is True
    assert drive.folders == [FOLDER_NAME]
    ((folder, name, data, mode),) = drive.uploads
    assert (folder, name, mode) == ("folder1", DUMP_NAME + ".enc", 0o600)
    assert b"whole database" not in data
    assert decrypt_bytes(data, KEY) == dump.read_bytes()
    row = _row(db_session)
    assert row.last_offsite_at == NOW
    assert row.last_offsite_error is None


def test_the_encrypted_temp_file_is_removed(db_session, key, connected, dump):
    offsite_copy(db_session, dump, client_factory=_factory(FakeDrive()), now=NOW)
    assert [p.name for p in dump.parent.iterdir()] == [DUMP_NAME]


def test_the_temp_file_is_removed_when_the_upload_fails(db_session, key, connected, dump):
    drive = FakeDrive()
    drive.fail_on["upload"] = DriveError("drive upload rejected (status 500)")
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is False
    assert [p.name for p in dump.parent.iterdir()] == [DUMP_NAME]
    assert _row(db_session).last_offsite_error == "drive upload rejected (status 500)"


def test_no_key_is_recorded_without_touching_google(db_session, connected, dump, monkeypatch):
    monkeypatch.setattr(app_config, "backup_encryption_key", None)
    row = _row(db_session)
    row.last_offsite_at = EARLIER
    db_session.commit()
    calls = []
    assert offsite_copy(db_session, dump, client_factory=_factory(FakeDrive(), calls), now=NOW) is False
    assert calls == []
    row = _row(db_session)
    assert row.last_offsite_error == NO_KEY == "set BACKUP_ENCRYPTION_KEY in .env"
    assert row.last_offsite_at == EARLIER


def test_google_not_connected_is_recorded(db_session, key, dump):
    calls = []
    assert offsite_copy(db_session, dump, client_factory=_factory(FakeDrive(), calls), now=NOW) is False
    assert calls == []
    assert _row(db_session).last_offsite_error == NOT_CONNECTED == "connect Google in Settings"
    assert _row(db_session).last_offsite_at is None


def test_a_revoked_google_connection_suggests_reconnecting(db_session, key, connected, dump):
    def factory(db):
        raise GoogleAuthError("google token request rejected (status 400)")

    assert offsite_copy(db_session, dump, client_factory=factory, now=NOW) is False
    assert _row(db_session).last_offsite_error == (
        "google token request rejected (status 400); reconnect Google in Settings"
    )


def test_drive_errors_are_recorded_and_keep_the_last_success(db_session, key, connected, dump):
    row = _row(db_session)
    row.last_offsite_at = EARLIER
    db_session.commit()
    drive = FakeDrive()
    drive.fail_on["folder"] = DriveError("drive folder lookup rejected (status 403); reconnect Google")
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is False
    row = _row(db_session)
    assert row.last_offsite_error == "drive folder lookup rejected (status 403); reconnect Google"
    assert row.last_offsite_at == EARLIER


def test_an_oversized_dump_is_recorded(db_session, key, connected, dump, monkeypatch):
    monkeypatch.setattr("app.services.backup.crypto.MAX_ENCRYPT_BYTES", 4)
    drive = FakeDrive()
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is False
    assert drive.uploads == []
    assert "limit for the off-site copy" in _row(db_session).last_offsite_error
    assert [p.name for p in dump.parent.iterdir()] == [DUMP_NAME]


def test_an_unexpected_crash_records_only_its_type(db_session, key, connected, dump, caplog):
    drive = FakeDrive()
    drive.fail_on["upload"] = RuntimeError("response body with secrets")
    with caplog.at_level(logging.WARNING):
        assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is False
    assert _row(db_session).last_offsite_error == "off-site copy failed unexpectedly (RuntimeError)"


def test_a_pruning_failure_still_counts_the_upload(db_session, key, connected, dump):
    drive = FakeDrive()
    drive.fail_on["list"] = DriveError("drive list rejected (status 500)")
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is False
    row = _row(db_session)
    assert row.last_offsite_at == NOW
    assert row.last_offsite_error == (
        "copy uploaded, but old Drive copies were not removed: drive list rejected (status 500)"
    )


def test_recording_failure_never_raises(db_session, key, connected, dump, monkeypatch, caplog):
    def broken(db):
        raise RuntimeError("database down")

    monkeypatch.setattr(offsite, "get_settings", broken)
    with caplog.at_level(logging.ERROR):
        assert offsite_copy(db_session, dump, client_factory=_factory(FakeDrive()), now=NOW) is True
    assert "could not record the off-site copy outcome" in caplog.text


def test_keeps_the_newest_thirty_copies(db_session, key, connected, dump):
    old = [DriveFile(f"old{day}", _copy_name(day)) for day in range(30, 0, -1)]  # newest first
    drive = FakeDrive(old)
    assert offsite_copy(db_session, dump, client_factory=_factory(drive), now=NOW) is True
    # 30 old + 1 new: the oldest one goes.
    assert drive.deleted == ["old1"]
    assert KEEP_OFFSITE == 30


def test_pruning_only_touches_copy_names_and_never_the_new_upload():
    others = [DriveFile("notes", "notes.txt"), DriveFile("plain", "tracker-20260901T073000Z.dump")]
    copies = [DriveFile(f"c{i}", _copy_name(i)) for i in range(5, 0, -1)]
    drive = FakeDrive([*others, *copies])
    assert prune_offsite(drive, "folder1", keep_id="c5", keep=2) == 3
    assert drive.deleted == ["c3", "c2", "c1"]
    # Drive's createdTime order put the just-uploaded copy last: it is still kept.
    drive = FakeDrive(copies[1:] + copies[:1])
    prune_offsite(drive, "folder1", keep_id="c5", keep=2)
    assert "c5" not in drive.deleted


def test_after_nightly_backup_runs_the_copy_with_the_real_drive_client(db_session, dump, monkeypatch):
    assert inspect.signature(offsite_copy).parameters["client_factory"].default is google_drive_client
    seen = []
    monkeypatch.setattr(offsite, "offsite_copy", lambda *args, **kwargs: seen.append((args, kwargs)))
    offsite.after_nightly_backup(db_session, dump)
    assert seen == [((db_session, dump), {})]


def test_status_reports_configuration(db_session, monkeypatch):
    monkeypatch.setattr(app_config, "backup_encryption_key", None)
    row = _row(db_session)
    row.last_backup_at = NOW
    row.last_offsite_error = NO_KEY
    db_session.commit()
    assert backup_status(db_session) == {
        "last_backup_at": NOW,
        "last_backup_error": None,
        "last_offsite_at": None,
        "last_offsite_error": NO_KEY,
        "offsite_configured": False,
    }
    monkeypatch.setattr(app_config, "backup_encryption_key", KEY)
    assert backup_status(db_session)["offsite_configured"] is False  # Google not connected
    store_token(db_session, {"refresh_token": "refresh"}, scopes="drive.file")
    assert backup_status(db_session)["offsite_configured"] is True
    monkeypatch.setattr(app_config, "backup_encryption_key", None)
    assert backup_status(db_session)["offsite_configured"] is False


def test_end_to_end_with_the_real_drive_client_on_a_fake_transport(db_session, key, connected, dump):
    from app.services.backup.drive_client import GoogleDriveClient
    from tests.services.backup.test_drive_client import FakeDrive as FakeDriveServer

    server = FakeDriveServer()
    server.folders = ["folder7"]
    client = GoogleDriveClient("tok", transport=server.transport())
    assert offsite_copy(db_session, dump, client_factory=lambda db: client, now=NOW) is True
    methods = [(r.method, r.url.params.get("uploadType")) for r in server.requests]
    assert methods == [("GET", None), ("POST", "multipart"), ("GET", None)]
    assert DUMP_NAME.encode() + b".enc" in server.bodies[1]
    assert b"whole database" not in server.bodies[1]
    assert _row(db_session).last_offsite_at == NOW
