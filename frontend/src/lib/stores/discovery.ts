import { writable } from "svelte/store";
import { getScanStatus } from "../api/discovery";
import type { ScanStatus } from "../types/discovery";

/** The latest scan status (Inbox count, scanning, last scan); null until first loaded. */
export const discoveryStatus = writable<ScanStatus | null>(null);

/**
 * Reloads the scan status into `discoveryStatus` and returns it. On any
 * failure the previous value stays and null is returned; it never throws,
 * so the sidebar badge and dashboard widget can call it freely.
 */
export async function refreshDiscoveryStatus(): Promise<ScanStatus | null> {
  try {
    const status = await getScanStatus();
    discoveryStatus.set(status);
    return status;
  } catch {
    return null;
  }
}
