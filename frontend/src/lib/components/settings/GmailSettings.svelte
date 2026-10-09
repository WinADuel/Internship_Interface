<script lang="ts">
  import { untrack } from "svelte";
  import { ApiError } from "../../api/client";
  import { CONNECT_GMAIL_URL } from "../../api/email";
  import { updateSettings } from "../../api/settings";
  import { formatDateTime } from "../../format";
  import { refreshEmailStatus, runEmailSync, syncSummary } from "../../stores/email";
  import { showToast } from "../../stores/toast";
  import type { AppSettings } from "../../types/contact";

  let { settings, onsaved }: { settings: AppSettings; onsaved?: (settings: AppSettings) => void } = $props();

  // Limits from backend `schemas/settings.py`.
  const MINUTES_MIN = 15;
  const MINUTES_MAX = 240;
  const LOOKBACK_MAX = 90;

  // Edited locally from the settings at mount; saving refreshes them.
  let enabled = $state(false);
  let minutes = $state<number | null>(30);
  let lookback = $state<number | null>(30);
  let autoApply = $state(false);
  let lastSyncAt = $state<string | null>(null);
  let lastError = $state<string | null>(null);

  function fill(s: AppSettings) {
    enabled = s.gmailSyncEnabled;
    minutes = s.gmailSyncMinutes;
    lookback = s.gmailLookbackDays;
    autoApply = s.gmailAutoApply;
    lastSyncAt = s.gmailLastSyncAt;
    lastError = s.gmailLastError;
  }
  untrack(() => fill(settings));

  const granted = $derived(settings.gmailGranted);
  // Sync now needs the saved state: Gmail granted and sync turned on.
  const canSync = $derived(settings.gmailGranted && settings.gmailSyncEnabled);

  let saving = $state(false);
  let formError = $state<string | null>(null);

  const whole = (n: number | null, min: number, max: number) =>
    typeof n === "number" && Number.isInteger(n) && n >= min && n <= max;

  async function save(event: SubmitEvent) {
    event.preventDefault();
    formError = null;
    if (!whole(minutes, MINUTES_MIN, MINUTES_MAX)) {
      formError = `Check every: a whole number of minutes from ${MINUTES_MIN} to ${MINUTES_MAX}.`;
      return;
    }
    if (!whole(lookback, 1, LOOKBACK_MAX)) {
      formError = `Look back: a whole number of days from 1 to ${LOOKBACK_MAX}.`;
      return;
    }
    saving = true;
    try {
      const saved = await updateSettings({
        gmailSyncEnabled: enabled,
        gmailSyncMinutes: minutes as number,
        gmailLookbackDays: lookback as number,
        gmailAutoApply: autoApply,
      });
      fill(saved);
      showToast("Gmail settings saved.", "info");
      void refreshEmailStatus();
      onsaved?.(saved);
    } catch (err) {
      formError = err instanceof ApiError ? `Couldn't save Gmail settings: ${err.message}` : "Couldn't save Gmail settings.";
    } finally {
      saving = false;
    }
  }

  let syncing = $state(false);
  let announcement = $state("");

  async function sync() {
    syncing = true;
    announcement = "";
    try {
      const result = await runEmailSync();
      lastSyncAt = result.gmailLastSyncAt;
      lastError = result.gmailLastError;
      announcement = syncSummary(result);
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't sync Gmail: ${err.message}` : "Couldn't sync Gmail.");
    } finally {
      syncing = false;
    }
  }
</script>

<section class="gmail" aria-labelledby="gmail-heading">
  <h2 id="gmail-heading">Gmail</h2>
  <p class="muted">
    Optional and off by default. Gmail sync reads the sender, recipients, subject, date and Gmail's short preview
    of recent Inbox and Sent mail to spot application updates, contact replies, emails you sent to a contact, and
    applications to companies you don't track yet. It keeps the sender, subject, date and preview only for emails
    it suggests an update from: mail matching an application or contact, and application-system mail (such as
    Greenhouse or Lever) from a company you don't track yet. Message bodies are never downloaded, other mail
    leaves no trace, and no email goes to Claude.
  </p>

  {#if granted}
    <p class="connected">Gmail: Connected</p>
  {:else}
    <p>
      <!-- Sync on without the permission: it was lost (Google revoked it, or a Drive-only reconnect dropped it). -->
      <a class="connect" href={CONNECT_GMAIL_URL}>{settings.gmailSyncEnabled ? "Reconnect Gmail" : "Connect Gmail"}</a>
      <span class="muted small">
        Google asks for read-only access to your mail. As a personal app it shows a “Google hasn't verified this
        app” screen first: choose Advanced, then continue.
      </span>
    </p>
  {/if}

  <form aria-label="Gmail settings" novalidate onsubmit={save}>
    <label class="check"><input type="checkbox" bind:checked={enabled} /> Sync Gmail</label>
    <label>
      Check every (minutes)
      <input type="number" required min={MINUTES_MIN} max={MINUTES_MAX} step="5" bind:value={minutes} />
    </label>
    <label>
      First sync looks back (days)
      <input type="number" required min="1" max={LOOKBACK_MAX} bind:value={lookback} />
    </label>
    <div class="field">
      <label class="check"><input type="checkbox" bind:checked={autoApply} /> Apply some updates automatically</label>
      <p class="muted small">
        Confirmations, contact replies and emails you sent are applied without asking; rejections, interviews,
        assessments and offers always wait for you.
      </p>
    </div>
    {#if formError}<p class="error" role="alert">{formError}</p>{/if}
    <button type="submit" disabled={saving}>Save Gmail settings</button>
  </form>

  <p>Last sync: {lastSyncAt ? formatDateTime(lastSyncAt) : "never"}</p>
  {#if lastError}
    <p class="error">Last sync failed: {lastError}</p>
    {#if granted}<p><a href={CONNECT_GMAIL_URL}>Reconnect Gmail</a></p>{/if}
  {/if}
  <button type="button" onclick={sync} disabled={syncing || !canSync}>{syncing ? "Syncing…" : "Sync now"}</button>
  {#if !canSync}
    <p class="muted small">
      {granted ? "Turn on Sync Gmail and save to sync." : "Connect Gmail first, then turn on Sync Gmail."}
    </p>
  {/if}
  <p class="status" role="status">{announcement}</p>
</section>

<style>
  .gmail { max-width: 40rem; margin-bottom: 1.5rem; }
  .muted { color: #666; }
  .small { font-size: 0.85rem; }
  .connected { font-weight: 600; color: #1e5b26; }
  .connect { font-weight: 600; margin-right: 0.4rem; }
  form { display: flex; flex-direction: column; gap: 0.6rem; margin: 0.75rem 0; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  .field p { margin: 0; }
  .check { display: flex; align-items: center; gap: 0.4rem; }
  input[type="number"] { width: 5rem; margin-left: 0.5rem; }
  .error { color: #b3261e; overflow-wrap: anywhere; }
  button[type="submit"] { align-self: flex-start; }
  .status:empty { display: none; }
</style>
