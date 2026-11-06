<script lang="ts">
  import { onMount } from "svelte";
  import { listPostings } from "../../api/discovery";
  import { postingLabel, postingWhen } from "../../discovery/format";
  import type { Posting } from "../../types/discovery";

  // The top of the Inbox by Best match (Phase 5 spec §6).
  const SHOWN = 5;

  let items = $state<Posting[]>([]);
  let total = $state(0);
  let loaded = $state(false);
  let failed = $state(false);
  let loading = $state(false);

  async function load() {
    loading = true;
    try {
      const page = await listPostings("inbox", { limit: SHOWN, sort: "best" });
      items = page.items;
      total = page.total;
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
      loading = false;
    }
  }

  onMount(() => {
    void load();
  });

  const now = $derived(new Date());
</script>

<!-- Postings come from lists, job boards and pasted pages: plain interpolation only. -->
<div class="widget">
  {#if failed}
    <p class="empty">Couldn't load new postings.</p>
    <button type="button" onclick={load} disabled={loading}>Retry</button>
  {:else if loaded && total === 0}
    <p class="empty">No new matches. Adjust filters in <a href="#/settings">Settings</a>.</p>
  {:else if loaded}
    <a class="count" href="#/discover">{total} new {total === 1 ? "match" : "matches"}</a>
    <ul>
      {#each items as p (p.id)}
        <li>
          <a href="#/discover">{postingLabel(p)}</a>
          <span class="when">{postingWhen(p, now)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .count { display: inline-flex; margin-bottom: 0.5rem; padding: 0.1rem 0.5rem; border-radius: var(--radius-sm); background: var(--primary); color: var(--primary-foreground); font-size: 0.75rem; font-weight: 600; }
  .count:hover { text-decoration: none; opacity: 0.9; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; padding: 0.55rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; overflow-wrap: anywhere; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  li a { color: var(--foreground); font-weight: 500; }
  .when { flex: none; color: var(--muted-foreground); font-size: 0.75rem; white-space: nowrap; }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0 0 0.5rem; }
</style>
