<script lang="ts">
  import { applications } from "../../stores/applications";
  import { bucketApplications, type Bucket } from "../../dashboard/widgets";
  import StatusBadge from "../StatusBadge.svelte";

  let {
    limit = 3,
    onsettingschange,
  }: { limit?: number; onsettingschange?: (settings: { limit: number }) => void } = $props();

  const buckets = $derived(bucketApplications($applications));
  const titles: Record<Bucket, string> = { undone: "Undone", workingOn: "Working on", completed: "Completed" };
  const order: Bucket[] = ["undone", "workingOn", "completed"];

  function onChange(event: Event) {
    onsettingschange?.({ limit: Number((event.currentTarget as HTMLSelectElement).value) });
  }
</script>

<div class="widget">
  <label class="setting">
    Per bucket
    <select value={String(limit)} onchange={onChange} aria-label="Items per bucket">
      <option value="3">3</option>
      <option value="5">5</option>
      <option value="10">10</option>
    </select>
  </label>
  {#each order as bucket (bucket)}
    <section aria-label={titles[bucket]}>
      <h3>{titles[bucket]} ({buckets[bucket].length})</h3>
      {#if buckets[bucket].length === 0}
        <p class="empty">Nothing here.</p>
      {:else}
        <ul>
          {#each buckets[bucket].slice(0, limit) as app (app.id)}
            <li>{app.company} — {app.roleTitle} <StatusBadge status={app.status} /></li>
          {/each}
        </ul>
        {#if buckets[bucket].length > limit}
          <p class="more">+{buckets[bucket].length - limit} more</p>
        {/if}
      {/if}
    </section>
  {/each}
</div>

<style>
  .setting { display: flex; align-items: center; justify-content: flex-end; gap: 0.4rem; font-size: 0.75rem; color: var(--muted-foreground); margin-bottom: 0.25rem; }
  .setting select { font-size: 0.75rem; padding: 0.15rem 0.4rem; }
  section + section { margin-top: 0.4rem; }
  h3 { margin: 0.5rem 0 0.3rem; font-size: 0.72rem; font-weight: 600; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: 0.05em; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; }
  li:first-child { border-top: 0; }
  .empty, .more { color: var(--muted-foreground); font-size: 0.8rem; margin: 0; }
</style>
