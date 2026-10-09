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
  import { bestScore, postingLabel, TOP_PICKS_SCORE } from "../../discovery/format";
  import { upsertApplication } from "../../stores/applications";
  import { refreshDiscoveryStatus } from "../../stores/discovery";
  import { showToast } from "../../stores/toast";
  import type { Posting, PostingSort, PostingView } from "../../types/discovery";
  import PostingRow, { type PostingAction } from "./PostingRow.svelte";

  // `sort` and `topPicksOnly` apply to the Inbox only; bound so the choice outlives a reload.
  let {
    view,
    sort = $bindable("best"),
    topPicksOnly = $bindable(false),
  }: { view: PostingView; sort?: PostingSort; topPicksOnly?: boolean } = $props();

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
  /** Inbox only: how many Inbox postings are Top picks; null until loaded. */
  let topPicks = $state<number | null>(null);
  const now = new Date();
  // Bumped by every fresh load; an older answer (or a page for an older list) is dropped.
  let generation = 0;

  function errorText(err: unknown): string | null {
    return err instanceof ApiError ? err.message : null;
  }

  function query(offset: number) {
    if (view !== "inbox") return { offset };
    return topPicksOnly ? { offset, sort, minScore: TOP_PICKS_SCORE } : { offset, sort };
  }

  const isTopPick = (posting: Posting) => (bestScore(posting) ?? 0) >= TOP_PICKS_SCORE;

  /** Keeps the Top picks count in step with rows leaving (negative) or coming back. */
  function countTopPicks(postings: Posting[], sign: 1 | -1) {
    if (topPicks === null) return;
    topPicks = Math.max(0, topPicks + sign * postings.filter(isTopPick).length);
  }

  async function load() {
    const request = ++generation;
    loading = true;
    loadError = null;
    try {
      const page = await listPostings(view, query(0));
      if (request !== generation) return;
      items = page.items;
      total = page.total;
      topPicks = page.topPicks;
    } catch (err) {
      if (request !== generation) return;
      const message = errorText(err);
      loadError = message ? `Couldn't load postings: ${message}` : "Couldn't load postings.";
    } finally {
      if (request === generation) loading = false;
    }
  }

  async function loadMore() {
    const request = generation;
    loadingMore = true;
    try {
      // Rows removed by actions have left this view on the server too, so the
      // count shown is the right offset; a repeated id is skipped anyway.
      const page = await listPostings(view, query(items.length));
      if (request !== generation) return;
      const known = new Set(items.map((p) => p.id));
      items = [...items, ...page.items.filter((p) => !known.has(p.id))];
      total = page.total;
      topPicks = page.topPicks;
    } catch (err) {
      if (request === generation) showToast(errorText(err) ?? "Couldn't load more postings.");
    } finally {
      loadingMore = false;
    }
  }

  function setSort(next: PostingSort) {
    if (sort === next) return;
    sort = next;
    void load();
  }

  function toggleTopPicks() {
    topPicksOnly = !topPicksOnly;
    void load();
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
    countTopPicks([posting], -1);
    try {
      await call(action, posting);
    } catch (err) {
      const at = Math.min(index, items.length);
      items = [...items.slice(0, at), posting, ...items.slice(at)];
      total += 1;
      countTopPicks([posting], 1);
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
        const gone = new Set(failed.map((p) => p.id));
        countTopPicks(shown.filter((p) => !gone.has(p.id)), -1);
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

{#if view === "inbox"}
  <div class="ranking">
    <div class="sort" role="group" aria-label="Order">
      <button type="button" aria-pressed={sort === "best"} onclick={() => setSort("best")}>Best match</button>
      <button type="button" aria-pressed={sort === "newest"} onclick={() => setSort("newest")}>Newest</button>
    </div>
    <button type="button" class="chip" aria-pressed={topPicksOnly} onclick={toggleTopPicks}>
      Top picks{#if topPicks !== null}{" "}<span class="n">{topPicks}</span>{/if}
    </button>
  </div>
{/if}

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
  {#if view === "inbox" && topPicksOnly}
    <p class="muted">
      No Top picks (score {TOP_PICKS_SCORE}+) right now. Tune your ranking preferences in
      <a href="#/settings">Settings</a>.
    </p>
  {:else}
    <p class="muted">{EMPTY[view]}</p>
  {/if}
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
  .ranking { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; }
  .sort { display: inline-flex; }
  .sort button { font: inherit; font-size: 0.85rem; padding: 0.25rem 0.7rem; border: 1px solid #bbb; background: #fff; cursor: pointer; }
  .sort button:first-child { border-radius: 6px 0 0 6px; }
  .sort button:last-child { border-radius: 0 6px 6px 0; border-left: 0; }
  .sort button[aria-pressed="true"] { background: #1a5fb4; border-color: #1a5fb4; color: #fff; }
  .chip { display: inline-flex; align-items: center; gap: 0.35rem; font: inherit; font-size: 0.85rem; padding: 0.25rem 0.75rem; border: 1px solid #bbb; border-radius: 999px; background: #fff; cursor: pointer; }
  .chip[aria-pressed="true"] { background: #d7f0dc; border-color: #2e7d32; color: #14532d; font-weight: 600; }
  .chip .n { min-width: 1.2rem; padding: 0 0.35rem; border-radius: 999px; background: #e0e0e0; color: #222; font-size: 0.75rem; text-align: center; }
  .ranking button:focus-visible { outline: 2px solid #1a5fb4; outline-offset: 1px; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.5rem; }
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .error { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; color: #b3261e; }
  .more { margin-top: 0.75rem; }
</style>
