<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { ApiError } from "../../api/client";
  import { CONNECT_GMAIL_URL, listGmailAccounts, removeGmailAccount } from "../../api/email";
  import { inboxLabel } from "../../email/format";
  import { updateSettings } from "../../api/settings";
  import { formatDateTime } from "../../format";
  import { refreshEmailStatus, runEmailSync, syncSummary } from "../../stores/email";
  import { showToast } from "../../stores/toast";
  import type { AppSettings } from "../../types/contact";
  import type { GmailAccount } from "../../types/email";

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

  // The connected inboxes; null until the first list arrives.
  let accounts = $state<GmailAccount[] | null>(null);
  let accountsFailed = $state(false);
  let removing = $state<number | null>(null);
  // Bumped when a list request starts and when a removal or Sync now changes
  // the list: an answer is kept only if nothing newer happened meanwhile, so a
  // slow list can't bring back an inbox just removed.
  let accountsSeq = 0;

  // Reconnect on an inbox without an address yet (carried over from before
  // inboxes had addresses) names it, so the consent gives that inbox its
  // address and new sign-in instead of adding a second line for the account.
  const reconnectUrl = (account: GmailAccount) =>
    account.email ? CONNECT_GMAIL_URL : `${CONNECT_GMAIL_URL}&inbox=${account.id}`;

  async function loadAccounts() {
    const seq = ++accountsSeq;
    accountsFailed = false;
    try {
      const rows = await listGmailAccounts();
      if (seq === accountsSeq) accounts = rows;
    } catch {
      if (seq === accountsSeq) accountsFailed = true;
    }
  }

  onMount(() => {
    void loadAccounts();
  });

  async function remove(account: GmailAccount) {
    const name = account.email ?? "this Gmail inbox";
    if (!window.confirm(`Remove ${name}? Its email updates are deleted from the tracker. Changes you already accepted stay.`)) {
      return;
    }
    removing = account.id;
    try {
      await removeGmailAccount(account.id);
      accountsSeq += 1;
      accounts = (accounts ?? []).filter((a) => a.id !== account.id);
      showToast(`Removed ${name}.`, "info");
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't remove the inbox: ${err.message}` : "Couldn't remove the inbox.");
      // Already gone (404): show the list as the server has it.
      if (err instanceof ApiError && err.status === 404) void loadAccounts();
    } finally {
      removing = null;
      // The pending count and the inbox list behind the nav badge and email cards changed.
      void refreshEmailStatus();
    }
  }

  // Once the list is here it decides; until then the settings' flag does.
  const granted = $derived(accounts !== null ? accounts.length > 0 : settings.gmailGranted);
  // Sync now needs the saved state: Gmail granted and sync turned on.
  const canSync = $derived(granted && settings.gmailSyncEnabled);

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
    // The inboxes as this sync left them, unless a removal or a newer list
    // came meanwhile (it would bring back an inbox just removed).
    const seq = ++accountsSeq;
    try {
      const result = await runEmailSync();
      if (seq === accountsSeq) accounts = result.accounts;
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

  <h3 id="gmail-inboxes-heading">Inboxes</h3>
  {#if accounts === null && accountsFailed}
    <p class="error">Couldn't load your inboxes. <button type="button" onclick={loadAccounts}>Retry</button></p>
  {:else if accounts === null}
    <p class="muted">Loading inboxes…</p>
  {:else if accounts.length === 0}
    <p class="muted">No inbox connected.</p>
  {:else}
    <ul class="inboxes" aria-labelledby="gmail-inboxes-heading">
      {#each accounts as account (account.id)}
        <li>
          <span class="address" class:pending-address={!account.email}>{inboxLabel(account)}</span>
          <span class="muted small">Last sync: {account.lastSyncAt ? formatDateTime(account.lastSyncAt) : "never"}</span>
          {#if account.lastError}<span class="error small">{account.lastError}</span>{/if}
          <span class="inbox-actions">
            <a href={reconnectUrl(account)} aria-label="Reconnect {inboxLabel(account)}">Reconnect</a>
            <button
              type="button"
              aria-label="Remove {inboxLabel(account)}"
              disabled={removing === account.id}
              onclick={() => remove(account)}
            >
              Remove
            </button>
          </span>
        </li>
      {/each}
    </ul>
  {/if}
  <p>
    <a class="connect" href={CONNECT_GMAIL_URL}>{granted ? "Add another inbox" : "Connect Gmail"}</a>
    <span class="muted small">
      Google asks which account to use and for read-only access to its mail. As a personal app it shows a
      “Google hasn't verified this app” screen first: choose Advanced, then continue.
    </span>
  </p>
  {#if accounts?.length}
    <p class="muted small">
      Remove deletes that inbox's email updates from the tracker but doesn't withdraw the app's access at Google. To
      withdraw it completely, also remove the app at
      <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer"
        >myaccount.google.com/permissions</a
      >.
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
  {#if lastError}<p class="error">Last sync failed: {lastError}</p>{/if}
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
  h3 { font-size: 1rem; margin: 0.75rem 0 0.4rem; }
  .inboxes { list-style: none; padding: 0; margin: 0 0 0.5rem; display: flex; flex-direction: column; gap: 0.4rem; }
  .inboxes li { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.45rem 0.6rem; border: 1px solid #ddd; border-radius: 6px; min-width: 0; }
  .address { font-weight: 600; overflow-wrap: anywhere; }
  .pending-address { font-weight: 400; font-style: italic; }
  .inbox-actions { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; margin-top: 0.15rem; }
  .inbox-actions button { font-size: 0.85rem; padding: 0.15rem 0.6rem; }
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
