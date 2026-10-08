<script lang="ts">
  import { tick } from "svelte";
  import PasteLink from "../lib/components/discovery/PasteLink.svelte";
  import PostingList from "../lib/components/discovery/PostingList.svelte";
  import ScanHeader from "../lib/components/discovery/ScanHeader.svelte";
  import type { PostingView } from "../lib/types/discovery";

  type Tab = PostingView | "watchlist";

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: "inbox", label: "Inbox" },
    { id: "saved", label: "Saved" },
    { id: "dismissed", label: "Dismissed" },
    { id: "watchlist", label: "Watchlist" },
  ];

  let tab = $state<Tab>("inbox");
  // Bumped to remount (and so reload) the open list, e.g. after a scan finishes.
  let reloads = $state(0);
  let tabButtons: HTMLButtonElement[] = $state([]);

  function reload() {
    reloads += 1;
  }

  /** A pasted posting lands in Saved: show that list, freshly loaded. */
  function showSaved() {
    if (tab === "saved") reload();
    else tab = "saved";
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
</script>

<h1>Discover</h1>
<ScanHeader onfinished={reload} />
<PasteLink onsaved={showSaved} />

<div class="tabs" role="tablist" aria-label="Postings">
  {#each TABS as t, i (t.id)}
    <button
      type="button"
      role="tab"
      id="discover-tab-{t.id}"
      aria-selected={tab === t.id}
      aria-controls="discover-panel"
      tabindex={tab === t.id ? 0 : -1}
      bind:this={tabButtons[i]}
      onclick={() => (tab = t.id)}
      onkeydown={(event) => onTabKeydown(event, i)}
    >
      {t.label}
    </button>
  {/each}
</div>

<div class="panel" role="tabpanel" id="discover-panel" aria-labelledby="discover-tab-{tab}">
  {#if tab === "watchlist"}
    <p class="muted">The company watchlist is coming next.</p>
  {:else}
    {#key `${tab}:${reloads}`}
      <PostingList view={tab} />
    {/key}
  {/if}
</div>

<style>
  .tabs { display: flex; flex-wrap: wrap; gap: 0.25rem; border-bottom: 1px solid #ddd; margin-bottom: 0.75rem; }
  .tabs button { border: 1px solid transparent; border-bottom: 0; background: none; padding: 0.4rem 0.9rem; border-radius: 6px 6px 0 0; cursor: pointer; font: inherit; }
  .tabs button[aria-selected="true"] { border-color: #ddd; background: #fff; font-weight: 600; margin-bottom: -1px; }
  .tabs button:focus-visible { outline: 2px solid #1a5fb4; }
  .muted { color: #555; }
</style>
