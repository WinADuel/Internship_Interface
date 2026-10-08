from datetime import datetime

from pydantic import BaseModel


class BackupStatusOut(BaseModel):
    """Settings → Backups (Phase 3 spec §4.4)."""

    last_backup_at: datetime | None
    last_backup_error: str | None
    last_offsite_at: datetime | None
    last_offsite_error: str | None
    # BACKUP_ENCRYPTION_KEY is set and Google is connected.
    offsite_configured: bool
