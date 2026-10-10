import { apiFetch } from "./client";
import { keysToCamel } from "./case";
import type { BackupStatus } from "../types/backup";

type Raw = Record<string, unknown>;

export async function getBackupStatus(): Promise<BackupStatus> {
  return keysToCamel<BackupStatus>(await apiFetch<Raw>("/api/backups/status"));
}

/**
 * Back up now: runs a local backup and resolves to the new status, even when
 * the dump failed (see `lastBackupError`). A 409 ApiError means another backup
 * is already running.
 */
export async function runBackupNow(): Promise<BackupStatus> {
  return keysToCamel<BackupStatus>(await apiFetch<Raw>("/api/backups/run", { method: "POST" }));
}
