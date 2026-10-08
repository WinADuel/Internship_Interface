"""The off-site copy (Phase 3 spec §4.4 part 2): after each nightly backup,
encrypt the dump and upload it to the app's "Internship Tracker Backups"
folder in Google Drive, keeping the newest KEEP_OFFSITE copies there.

It needs both BACKUP_ENCRYPTION_KEY and a Google connection; without either
the local dump still stands and the reason is recorded for Settings, the
same way sheet-sync errors are. The outcome is recorded, never raised."""

import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings as app_config
from app.services.backup.crypto import ENC_NAME_RE, BackupCryptoError, encrypt_file, encrypted_name
from app.services.backup.drive_client import FOLDER_NAME, DriveClient, DriveError, GoogleDriveClient
from app.services.backup.dump import clean_detail
from app.services.errors import GoogleAuthError
from app.services.google_docs_service import get_valid_access_token, is_google_connected
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

KEEP_OFFSITE = 30
NO_KEY = "set BACKUP_ENCRYPTION_KEY in .env"
NOT_CONNECTED = "connect Google in Settings"
_ERROR_DETAIL_LIMIT = 300

DriveClientFactory = Callable[[Session], DriveClient]


def google_drive_client(db: Session) -> DriveClient:
    return GoogleDriveClient(get_valid_access_token(db))


def offsite_configured(db: Session) -> bool:
    return bool(app_config.backup_encryption_key) and is_google_connected(db)


def prune_offsite(client: DriveClient, folder_id: str, keep_id: str, keep: int = KEEP_OFFSITE) -> int:
    """Delete all but the newest `keep` encrypted copies in the folder (never
    `keep_id`, the one just uploaded). Only files named exactly like a copy
    are touched. Returns how many were deleted."""
    copies = [f for f in client.list_files(folder_id) if ENC_NAME_RE.match(f.name)]
    doomed = [f for f in copies[max(1, keep) :] if f.id != keep_id]
    for f in doomed:
        client.delete(f.id)
    return len(doomed)


def _upload(db: Session, dump_path: Path, client_factory: DriveClientFactory) -> tuple[bool, str | None]:
    """Encrypt and upload. Returns (uploaded, error for Settings or None)."""
    key = app_config.backup_encryption_key
    if not key:
        return False, NO_KEY
    if not is_google_connected(db):
        return False, NOT_CONNECTED
    try:
        client = client_factory(db)
    except GoogleAuthError as exc:
        # Scrubbed by the service: status codes and exception types only.
        return False, f"{exc}; reconnect Google in Settings"

    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".offsite-", suffix=".enc", dir=dump_path.parent)  # mode 0600
        os.close(fd)
    except OSError as exc:
        return False, f"cannot write the encrypted copy: {clean_detail(exc.strerror or str(exc))}"
    tmp = Path(tmp_name)
    try:
        encrypt_file(dump_path, tmp, key)
        folder_id = client.find_or_create_folder(FOLDER_NAME)
        file_id = client.upload(folder_id, encrypted_name(dump_path.name), tmp)
    finally:
        tmp.unlink(missing_ok=True)
    logger.info("off-site copy uploaded: %s", encrypted_name(dump_path.name))
    try:
        deleted = prune_offsite(client, folder_id, file_id)
    except DriveError as exc:
        # The copy is safe; say so, but keep the failure visible in Settings.
        return True, f"copy uploaded, but old Drive copies were not removed: {exc}"
    if deleted:
        logger.info("off-site retention: deleted %d old copy(ies)", deleted)
    return True, None


def offsite_copy(
    db: Session,
    dump_path: Path,
    *,
    client_factory: DriveClientFactory = google_drive_client,
    now: datetime | None = None,
) -> bool:
    """Copy one dump off-site and record the outcome on the settings row:
    an upload sets `last_offsite_at`; `last_offsite_error` is cleared by a
    clean run. Never raises; returns whether the run was clean."""
    uploaded = False
    try:
        uploaded, error = _upload(db, Path(dump_path), client_factory)
    except (BackupCryptoError, DriveError) as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - the local backup already stands
        logger.exception("off-site copy crashed")
        # The message may quote a response; only the type is kept.
        error = f"off-site copy failed unexpectedly ({type(exc).__name__})"
    if error is not None:
        error = error[:_ERROR_DETAIL_LIMIT]
        logger.warning("off-site copy: %s", error)
    try:
        db.rollback()  # nothing of ours is pending; start from a clean transaction
        row = get_settings(db)
        if uploaded:
            row.last_offsite_at = now or datetime.now(timezone.utc)
        row.last_offsite_error = error
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the off-site copy outcome")
        db.rollback()
    return error is None


def after_nightly_backup(db: Session, dump_path: Path) -> None:
    """The db-backup job's step after each nightly dump."""
    offsite_copy(db, dump_path)


def backup_status(db: Session) -> dict:
    """For Settings → Backups."""
    row = get_settings(db)
    return {
        "last_backup_at": row.last_backup_at,
        "last_backup_error": row.last_backup_error,
        "last_offsite_at": row.last_offsite_at,
        "last_offsite_error": row.last_offsite_error,
        "offsite_configured": offsite_configured(db),
    }
