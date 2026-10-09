import { writable } from "svelte/store";
import { getApplication } from "../api/applications";
import { getContact } from "../api/contacts";
import { getEmailStatus, syncEmailNow } from "../api/email";
import type { EmailStatus, EmailSuggestion, EmailSyncResult } from "../types/email";
import { upsertApplication } from "./applications";
import { replaceContact } from "./contacts";

/** The latest Gmail sync status (pending count, last sync); null until first loaded. */
export const emailStatus = writable<EmailStatus | null>(null);

/**
 * Reloads the status into `emailStatus` and returns it. On failure the
 * previous value stays and null is returned; it never throws, so the nav
 * badge and the Needs Attention row can call it freely.
 */
export async function refreshEmailStatus(): Promise<EmailStatus | null> {
  try {
    const status = await getEmailStatus();
    emailStatus.set(status);
    return status;
  } catch {
    return null;
  }
}

/**
 * After an Accept: refresh the badge and the application or contact the
 * email changed, in the shared stores, so open boards and panels catch up.
 * Never throws; a store that misses an update catches up on its next load.
 */
export async function afterAccept(suggestion: EmailSuggestion): Promise<void> {
  const work: Promise<unknown>[] = [refreshEmailStatus()];
  if (suggestion.applicationId !== null) {
    work.push(getApplication(suggestion.applicationId).then(upsertApplication));
  }
  if (suggestion.contactId !== null) {
    work.push(getContact(suggestion.contactId).then(replaceContact));
  }
  await Promise.allSettled(work);
}

/** Sync now: runs a sync, stores the new status and returns the outcome. API errors are thrown. */
export async function runEmailSync(): Promise<EmailSyncResult> {
  const result = await syncEmailNow();
  emailStatus.set({
    gmailGranted: result.gmailGranted,
    gmailSyncEnabled: result.gmailSyncEnabled,
    gmailLastSyncAt: result.gmailLastSyncAt,
    gmailLastError: result.gmailLastError,
    pendingCount: result.pendingCount,
  });
  return result;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One sentence on what a Sync now did. */
export function syncSummary(result: EmailSyncResult): string {
  if (!result.ok) return `Gmail sync failed: ${result.gmailLastError ?? "unknown error"}`;
  let text = `Checked ${plural(result.fetched, "email", "emails")}: ${plural(result.suggested, "update", "updates")} found`;
  if (result.autoApplied) text += `, ${result.autoApplied} applied automatically`;
  return text + (result.more ? ". More mail is left for the next sync." : ".");
}
