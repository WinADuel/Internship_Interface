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
  .count { display: inline-block; font-weight: 600; margin-bottom: 0.4rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { padding: 0.25rem 0; font-size: 0.85rem; overflow-wrap: anywhere; }
  .when { color: #666; font-size: 0.75rem; margin-left: 0.25rem; }
  .empty { color: #666; font-size: 0.85rem; }
  button { font-size: 0.8rem; padding: 0.2rem 0.5rem; }
</style>
