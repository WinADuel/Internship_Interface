"""Backup routes (Phase 3 spec §4.4): the status for Settings → Backups, and
Back up now, which takes a manual local backup synchronously. Cookie auth
only; the Claude token is refused like on every other cookie route."""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_backup_dump, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.schemas.backup import BackupStatusOut
from app.services.backup.lock import backup_lock
from app.services.backup.offsite import backup_status
from app.services.backup.service import run_backup

router = APIRouter(
    prefix="/api/backups",
    tags=["backups"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/status", response_model=BackupStatusOut)
def get_backup_status(db: Session = Depends(get_db)):
    return BackupStatusOut(**backup_status(db))


@router.post("/run", response_model=BackupStatusOut)
def back_up_now(
    db: Session = Depends(get_db),
    dump: Callable[..., Path] = Depends(get_backup_dump),
):
    """Run a manual backup now and return the new status (a failure shows as
    `last_backup_error`). 409 while any other backup, nightly or pre-deploy
    included, holds the backup lock. Manual dumps stay local."""
    with backup_lock(db.get_bind().engine) as locked:
        if not locked:
            raise HTTPException(status_code=409, detail="a backup is already running")
        run_backup(
            db,
            "manual",
            database_url=settings.database_url,
            backup_dir=settings.backup_dir,
            dump=dump,
        )
    return BackupStatusOut(**backup_status(db))
