<script lang="ts">
  import { onMount } from "svelte";
  import { getBackupStatus, runBackupNow } from "../../api/backups";
  import { ApiError } from "../../api/client";
  import { timeAgo } from "../../discovery/format";
  import { formatDateTime } from "../../format";
  import { showToast } from "../../stores/toast";
  import type { BackupStatus } from "../../types/backup";

  let status = $state<BackupStatus | null>(null);
  let loadFailed = $state(false);
  let running = $state(false);
  // Re-render "2 hours ago" while the page stays open.
  let now = $state(new Date());
  // A Back up now result is fresher than a status load still in flight.
  let ranBackup = false;

  const message = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

  async function load() {
    try {
      const loaded = await getBackupStatus();
      if (!ranBackup) status = loaded;
    } catch (err) {
      if (!ranBackup) loadFailed = true;
      showToast(message(err, "Couldn't load the backup status."));
    }
  }

  onMount(() => {
    void load();
    const timer = setInterval(() => (now = new Date()), 60_000);
    return () => clearInterval(timer);
  });

  async function backUpNow() {
    running = true;
    try {
      const result = await runBackupNow();
      ranBackup = true;
      status = result;
      loadFailed = false;
      if (result.lastBackupError) showToast(`Backup failed: ${result.lastBackupError}`);
      else showToast("Backup complete.", "info");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) showToast("A backup is already running");
      else showToast(message(err, "Couldn't run the backup."));
    } finally {
      running = false;
    }
  }
</script>

<section aria-labelledby="backups-heading">
  <h2 id="backups-heading">Backups</h2>
  <p class="muted">
    Every night the server keeps a copy of your data and puts an encrypted copy in the "Internship Tracker Backups"
    folder in your Google Drive; Back up now adds an extra copy on the server only.
  </p>

  {#if status}
    <p>
      Last backup:
      {#if status.lastBackupAt}
        <time datetime={status.lastBackupAt} title={formatDateTime(status.lastBackupAt)}>{timeAgo(status.lastBackupAt, now)}</time>
      {:else}
        No backup yet
      {/if}
    </p>
    {#if status.lastBackupError}
      <p class="error">Latest backup failed: {status.lastBackupError}</p>
    {/if}

    {#if status.offsiteConfigured || status.lastOffsiteAt}
      <p>
        Last off-site copy:
        {#if status.lastOffsiteAt}
          <time datetime={status.lastOffsiteAt} title={formatDateTime(status.lastOffsiteAt)}>{timeAgo(status.lastOffsiteAt, now)}</time>
        {:else}
          none yet
        {/if}
      </p>
    {/if}
    {#if !status.offsiteConfigured}
      <p class="muted">
        Off-site copies to Google Drive are off. They start once Google is connected and BACKUP_ENCRYPTION_KEY is set
        in the server's .env file.
      </p>
    {:else if status.lastOffsiteError && status.lastOffsiteAt}
      <!-- An earlier copy is safe in Drive, so this is a warning, not a failure. -->
      <p class="warning">Off-site copy warning: {status.lastOffsiteError}</p>
    {:else if status.lastOffsiteError}
      <p class="error">Off-site copy failed: {status.lastOffsiteError}</p>
    {/if}
  {:else if loadFailed}
    <p class="muted">Backup status unavailable.</p>
  {/if}

  <button type="button" onclick={backUpNow} disabled={running}>{running ? "Backing up…" : "Back up now"}</button>
</section>

<style>
  .muted { color: #666; }
  p { overflow-wrap: anywhere; }
  .error { color: #a00; background: #fdecea; border: 1px solid #f5c2c0; padding: 0.5rem; }
  .warning { color: #6b4e00; background: #fff8e1; border: 1px solid #e0c060; padding: 0.5rem; }
</style>
