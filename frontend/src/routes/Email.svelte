<script lang="ts">
  import { onMount, tick } from "svelte";
  import { get } from "svelte/store";
  import { ApiError } from "../lib/api/client";
  import { listSuggestions } from "../lib/api/email";
  import SuggestionCard from "../lib/components/email/SuggestionCard.svelte";
  import { formatDateTime } from "../lib/format";
  import { emailStatus, refreshEmailStatus, runEmailSync, syncSummary } from "../lib/stores/email";
  import { showToast } from "../lib/stores/toast";
  import type { EmailSuggestion } from "../lib/types/email";

  type Tab = "pending" | "decided";
  const TABS: Array<{ id: Tab; label: string }> = [
    { id: "pending", label: "Pending" },
    { id: "decided", label: "Recent decisions" },
  ];
  const DECIDED_LIMIT = 50;
  const PENDING_LIMIT = 200; // the API's maximum

  let tab = $state<Tab>("pending");
  let tabButtons: HTMLButtonElement[] = $state([]);
  let items = $state<EmailSuggestion[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let syncing = $state(false);
  let statusFailed = $state(false);
  // Whether the last load hit the list's cap (more may be pending than shown).
  let capped = $state(false);
  let announcement = $state("");
  // Bumped on every load; an answer is applied only if it is still the latest.
  let latest = 0;

  async function load() {
    const request = ++latest;
    const state = tab;
    try {
      const rows = await listSuggestions({ state, limit: state === "pending" ? PENDING_LIMIT : DECIDED_LIMIT });
      if (request !== latest) return;
      items = rows;
      capped = state === "pending" && rows.length >= PENDING_LIMIT;
      failed = false;
    } catch (err) {
      if (request !== latest) return;
      items = [];
      failed = true;
      showToast(err instanceof ApiError ? `Couldn't load email updates: ${err.message}` : "Couldn't load email updates.");
    } finally {
      if (request === latest) loaded = true;
    }
  }

  $effect(() => {
    void tab; // reload when the tab changes
    loaded = false;
    void load();
  });

  async function loadStatus() {
    statusFailed = false;
    const result = await refreshEmailStatus();
    // null with a status stored means a newer request answered instead.
    statusFailed = result === null && get(emailStatus) === null;
  }

  onMount(() => {
    void loadStatus();
  });

  /** A card was decided: drop it from Pending (or show it decided) at once, then reload. */
  function onchanged(updated: EmailSuggestion | null) {
    if (updated !== null) {
      items = tab === "pending" ? items.filter((i) => i.id !== updated.id) : items.map((i) => (i.id === updated.id ? updated : i));
    }
    void load();
  }

  async function sync() {
    syncing = true;
    announcement = "";
    try {
      announcement = syncSummary(await runEmailSync());
      await load();
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't sync Gmail: ${err.message}` : "Couldn't sync Gmail.");
    } finally {
      syncing = false;
    }
  }

  async function onTabKeydown(event: KeyboardEvent, index: number) {
    const last = TABS.length - 1;
    const target =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (target === null) return;
    event.preventDefault();
    tab = TABS[target].id;
    await tick();
    tabButtons[target]?.focus();
  }

  const status = $derived($emailStatus);
  // The list is capped; say so when more are pending than it shows.
  const hiddenPending = $derived(capped && tab === "pending" && status !== null && status.pendingCount > items.length);
</script>

<h1>Email updates</h1>

<section class="sync" aria-label="Gmail sync">
  {#if !status && statusFailed}
    <p class="error">Couldn't load Gmail status. <button type="button" onclick={loadStatus}>Retry</button></p>
  {:else if status && !status.gmailGranted}
    <p>
      Gmail isn't connected.
      <a href="#/settings">Connect Gmail in Settings</a>
      to find application updates in your mail.
    </p>
  {:else if status && !status.gmailSyncEnabled}
    <p>Gmail sync is off. <a href="#/settings">Turn it on in Settings</a>.</p>
  {/if}
  {#if status}
    <p class="muted">
      Last checked: {status.gmailLastSyncAt ? formatDateTime(status.gmailLastSyncAt) : "never"}
    </p>
    {#if status.gmailLastError}<p class="error">Last sync failed: {status.gmailLastError}</p>{/if}
    {#if status.gmailGranted && status.gmailSyncEnabled}
      <button type="button" onclick={sync} disabled={syncing}>{syncing ? "Syncing…" : "Sync now"}</button>
    {/if}
  {/if}
  <p class="status" role="status">{announcement}</p>
</section>

<div class="tabs" role="tablist" aria-label="Email updates">
  {#each TABS as t, i (t.id)}
    <button
      type="button"
      role="tab"
      id="email-tab-{t.id}"
      aria-selected={tab === t.id}
      aria-controls="email-panel"
      tabindex={tab === t.id ? 0 : -1}
      bind:this={tabButtons[i]}
      onclick={() => (tab = t.id)}
      onkeydown={(event) => onTabKeydown(event, i)}
    >
      {t.label}{#if t.id === "pending" && status && status.pendingCount > 0}&nbsp;({status.pendingCount}){/if}
    </button>
  {/each}
</div>

<div class="panel" role="tabpanel" id="email-panel" aria-labelledby="email-tab-{tab}">
  {#if failed}
    <p class="empty">Couldn't load email updates. <button type="button" onclick={load}>Retry</button></p>
  {:else if !loaded}
    <p class="empty">Loading…</p>
  {:else if items.length === 0}
    <p class="empty">{tab === "pending" ? "No email updates to review." : "No decisions yet."}</p>
  {:else}
    {#if hiddenPending && status}
      <p class="muted">Showing the first {items.length} of {status.pendingCount}.</p>
    {/if}
    <div class="list">
      {#each items as s (s.id)}
        <SuggestionCard suggestion={s} {onchanged} />
      {/each}
    </div>
  {/if}
</div>

<style>
  .sync { max-width: 48rem; margin-bottom: 0.75rem; }
  .sync p { margin: 0 0 0.4rem; }
  .muted { color: #666; font-size: 0.9rem; }
  .error { color: #b3261e; overflow-wrap: anywhere; }
  .status:empty { display: none; }
  .tabs { display: flex; flex-wrap: wrap; gap: 0.25rem; border-bottom: 1px solid #ddd; margin-bottom: 0.75rem; }
  .tabs button { border: 1px solid transparent; border-bottom: 0; background: none; padding: 0.4rem 0.9rem; border-radius: 6px 6px 0 0; cursor: pointer; font: inherit; }
  .tabs button[aria-selected="true"] { border-color: #ddd; background: #fff; font-weight: 600; margin-bottom: -1px; }
  .tabs button:focus-visible { outline: 2px solid #1a5fb4; }
  .list { display: flex; flex-direction: column; gap: 0.6rem; max-width: 48rem; }
  .empty { color: #666; }
</style>
