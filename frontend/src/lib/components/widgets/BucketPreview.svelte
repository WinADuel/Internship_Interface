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
  .setting { font-size: 0.75rem; display: block; text-align: right; }
  h3 { margin: 0.5rem 0 0.25rem; font-size: 0.9rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { padding: 0.15rem 0; font-size: 0.85rem; }
  .empty, .more { color: #666; font-size: 0.8rem; margin: 0; }
</style>
