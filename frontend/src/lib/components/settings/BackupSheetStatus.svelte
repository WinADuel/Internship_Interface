<script lang="ts">
  import { ApiError } from "../../api/client";
  import { syncSheetNow } from "../../api/settings";
  import { formatDateTime } from "../../format";
  import { showToast } from "../../stores/toast";

  interface SheetStatus {
    backupSheetId: string | null;
    lastSheetSyncAt: string | null;
    lastSheetSyncError: string | null;
  }

  let { status }: { status: SheetStatus } = $props();

  let syncedAt = $state<string | null>(null);
  let error = $state<string | null>(null);
  let url = $state<string | null>(null);
  let syncing = $state(false);

  // Follow the parent's settings until a manual sync gives fresher values.
  $effect.pre(() => {
    syncedAt = status.lastSheetSyncAt;
    error = status.lastSheetSyncError;
    url = status.backupSheetId
      ? `https://docs.google.com/spreadsheets/d/${encodeURIComponent(status.backupSheetId)}`
      : null;
  });

  const needsGoogle = $derived(
    error !== null && (error === "google not connected" || error.includes("reconnect Google")),
  );

  async function sync() {
    syncing = true;
    try {
      const result = await syncSheetNow();
      syncedAt = result.lastSheetSyncAt;
      error = result.lastSheetSyncError;
      if (result.sheetUrl) url = result.sheetUrl;
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't sync the backup sheet.");
    } finally {
      syncing = false;
    }
  }
</script>

<section aria-labelledby="backup-sheet-heading">
  <h2 id="backup-sheet-heading">Backup sheet</h2>
  <p class="muted">A Google Sheet copy of your applications and contacts, refreshed after changes and nightly.</p>
  {#if url}
    <p><a href={url} target="_blank" rel="noopener noreferrer">Open backup sheet</a></p>
  {/if}
  <p>Last synced: {syncedAt ? formatDateTime(syncedAt) : "never"}</p>
  {#if error}
    <p class="error" role="alert">Last sync failed: {error}</p>
    {#if needsGoogle}
      <p><a href="/api/docs/google/authorize">Connect Google</a></p>
    {/if}
  {/if}
  <button type="button" onclick={sync} disabled={syncing}>Sync now</button>
</section>

<style>
  .muted { color: #666; }
  .error { color: #a00; background: #fdecea; border: 1px solid #f5c2c0; padding: 0.5rem; }
</style>
