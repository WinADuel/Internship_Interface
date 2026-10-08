<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../api/client";
  import {
    applyToPosting,
    dismissAllPostings,
    dismissPosting,
    listPostings,
    restorePosting,
    savePosting,
  } from "../../api/discovery";
  import { postingLabel } from "../../discovery/format";
  import { upsertApplication } from "../../stores/applications";
  import { refreshDiscoveryStatus } from "../../stores/discovery";
  import { showToast } from "../../stores/toast";
  import type { Posting, PostingView } from "../../types/discovery";
  import PostingRow, { type PostingAction } from "./PostingRow.svelte";

  let { view }: { view: PostingView } = $props();

  const EMPTY: Record<PostingView, string> = {
    inbox: "No new postings match your filters.",
    saved: "Nothing saved yet. Save postings from the Inbox or paste a link above.",
    dismissed: "Nothing dismissed.",
  };
  const VERBS: Record<PostingAction, string> = {
    save: "save",
    dismiss: "dismiss",
    apply: "apply to",
    remove: "remove",
    restore: "restore",
  };

  let items = $state<Posting[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  const now = new Date();

  function errorText(err: unknown): string | null {
    return err instanceof ApiError ? err.message : null;
  }

  async function load() {
    loading = true;
    loadError = null;
    try {
      const page = await listPostings(view, { offset: 0 });
      items = page.items;
      total = page.total;
    } catch (err) {
      const message = errorText(err);
      loadError = message ? `Couldn't load postings: ${message}` : "Couldn't load postings.";
    } finally {
      loading = false;
    }
  }

  async function loadMore() {
    loadingMore = true;
    try {
      // Rows removed by actions have left this view on the server too, so the
      // count shown is the right offset; a repeated id is skipped anyway.
      const page = await listPostings(view, { offset: items.length });
      const known = new Set(items.map((p) => p.id));
      items = [...items, ...page.items.filter((p) => !known.has(p.id))];
      total = page.total;
    } catch (err) {
      showToast(errorText(err) ?? "Couldn't load more postings.");
    } finally {
      loadingMore = false;
    }
  }

  onMount(() => {
    void load();
  });

  function call(action: PostingAction, posting: Posting): Promise<unknown> {
    switch (action) {
      case "save":
        return savePosting(posting.id);
      case "dismiss":
      case "remove":
        return dismissPosting(posting.id);
      case "restore":
        return restorePosting(posting.id);
      case "apply":
        return applyToPosting(posting.id).then((application) => {
          upsertApplication(application);
          showToast(`${postingLabel(posting)} is now in Applications as Applied.`, "info");
        });
    }
  }

  /** Removes the row at once; puts it back where it was if the server refuses. */
  async function act(posting: Posting, action: PostingAction) {
    const label = postingLabel(posting);
    if (action === "apply" && !window.confirm(`Add ${label} to your tracker as Applied today?`)) return;
    const index = items.findIndex((p) => p.id === posting.id);
    if (index === -1) return;
    items = items.filter((p) => p.id !== posting.id);
    total = Math.max(0, total - 1);
    try {
      await call(action, posting);
    } catch (err) {
      const at = Math.min(index, items.length);
      items = [...items.slice(0, at), posting, ...items.slice(at)];
      total += 1;
      const message = errorText(err);
      showToast(message ? `Couldn't ${VERBS[action]} ${label}: ${message}` : `Couldn't ${VERBS[action]} ${label}.`);
      return;
    }
    void refreshDiscoveryStatus();
    // Emptied a page while more remain: fetch the next ones instead of claiming the list is empty.
    if (items.length === 0 && total > 0) void load();
  }

  /** The backend takes at most this many ids per dismiss-all request. */
  const DISMISS_CHUNK = 500;
  let dismissing = $state(0); // how many postings a dismiss-all is clearing; 0 when idle

  async function dismissAllShown() {
    const shown = items;
    if (!shown.length || !window.confirm(`Dismiss all ${shown.length} ${shown.length === 1 ? "posting" : "postings"} shown?`)) return;
    items = [];
    dismissing = shown.length;
    try {
      // One request per chunk, in turn; a failed chunk's rows come back, the rest stay gone.
      let dismissed = 0;
      const failed: Posting[] = [];
      let failure: unknown = null;
      for (let at = 0; at < shown.length; at += DISMISS_CHUNK) {
        const chunk = shown.slice(at, at + DISMISS_CHUNK);
        try {
          dismissed += await dismissAllPostings(chunk.map((p) => p.id));
        } catch (err) {
          failed.push(...chunk);
          failure ??= err;
        }
      }
      if (failed.length === shown.length) {
        items = shown;
        const message = errorText(failure);
        showToast(message ? `Couldn't dismiss the postings: ${message}` : "Couldn't dismiss the postings.");
        return;
      }
      void refreshDiscoveryStatus();
      if (failed.length) {
        items = failed;
        total = Math.max(failed.length, total - (shown.length - failed.length));
        const message = errorText(failure);
        const lead = `Dismissed ${dismissed} of ${shown.length} postings. Couldn't dismiss the other ${failed.length}`;
        showToast(message ? `${lead}: ${message}` : `${lead}.`);
        return;
      }
      await load();
    } finally {
      dismissing = 0;
    }
  }
</script>

{#if dismissing && items.length === 0}
  <p class="muted" role="status">Dismissing {dismissing} {dismissing === 1 ? "posting" : "postings"}…</p>
{:else if loading}
  <p class="muted">Loading…</p>
{:else if loadError}
  <div class="error" role="alert">
    <span>{loadError}</span>
    <button type="button" onclick={load}>Retry</button>
  </div>
{:else if items.length === 0}
  <p class="muted">{EMPTY[view]}</p>
{:else}
  <div class="toolbar">
    <span class="muted">Showing {items.length} of {total}</span>
    {#if view === "inbox"}
      <button type="button" onclick={dismissAllShown}>Dismiss all shown</button>
    {/if}
  </div>
  <ul>
    {#each items as posting (posting.id)}
      <li><PostingRow {posting} {view} {now} onaction={(action) => act(posting, action)} /></li>
    {/each}
  </ul>
  {#if items.length < total}
    <button type="button" class="more" disabled={loadingMore} onclick={loadMore}>Load more</button>
  {/if}
{/if}

<style>
  .muted { color: #555; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.5rem; }
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .error { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; color: #b3261e; }
  .more { margin-top: 0.75rem; }
</style>
