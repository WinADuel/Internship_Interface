/** Settings → Backups (backend app/schemas/backup.py). Error texts are plain text: never render as HTML. */
export interface BackupStatus {
  lastBackupAt: string | null;
  lastBackupError: string | null;
  lastOffsiteAt: string | null;
  lastOffsiteError: string | null;
  /** BACKUP_ENCRYPTION_KEY is set on the server and Google is connected. */
  offsiteConfigured: boolean;
}
