"""One local backup run: dump, apply retention, record the outcome on the
settings row (Phase 3 spec §4.4). Used by the db-backup job; the
"Back up now" route can reuse `run_backup` with its own session."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.backup.dump import BackupError, run_dump
from app.services.backup.retention import prune
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

# A step run after a successful dump (e.g. the off-site copy). It records its
# own outcome; an exception from it is logged and never fails the local backup.
AfterBackup = Callable[[Session, Path], None]


@dataclass
class BackupResult:
    label: str
    path: Path | None = None  # the new dump, when it succeeded
    error: str | None = None  # why it failed, when it did
    deleted: list[Path] = field(default_factory=list)  # removed by retention
    status_recorded: bool = False  # the outcome reached the settings row

    @property
    def ok(self) -> bool:
        return self.error is None


def record_backup_outcome(db: Session, error: str | None, now: datetime) -> None:
    """Store the outcome on the settings row: a success sets the time and
    clears any old error; a failure keeps the last success time."""
    settings = get_settings(db)
    if error is None:
        settings.last_backup_at = now
    settings.last_backup_error = error
    db.commit()


def run_backup(
    db: Session,
    label: str,
    *,
    database_url: str,
    backup_dir: str | Path,
    now: datetime | None = None,
    dump: Callable[..., Path] = run_dump,
    after: AfterBackup | None = None,
) -> BackupResult:
    """Run one backup. Never raises: the outcome is in the result. A failure
    to record the outcome (database down) does not change `ok`."""
    now = now or datetime.now(timezone.utc)
    result = BackupResult(label=label)
    try:
        result.path = dump(database_url, backup_dir, label, now)
    except BackupError as exc:
        result.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - a backup run must report, not crash
        logger.exception("backup crashed")
        result.error = f"backup failed unexpectedly ({type(exc).__name__})"

    if result.ok:
        logger.info("%s backup written: %s", label, result.path)
        try:
            result.deleted = prune(backup_dir, label)
        except Exception:  # noqa: BLE001 - old files left behind are not a failed backup
            logger.exception("backup retention failed; old dumps were kept")
    else:
        logger.error("%s backup failed: %s", label, result.error)

    try:
        record_backup_outcome(db, result.error, now)
        result.status_recorded = True
    except Exception:  # noqa: BLE001 - e.g. the database is down; the dump result stands
        logger.exception("could not record the backup outcome in the database")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    if result.ok and after is not None:
        try:
            after(db, result.path)
        except Exception:  # noqa: BLE001
            logger.exception("step after the %s backup failed", label)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return result
