<script lang="ts">
  import { getRecentActivity } from "../../api/applications";
  import { relativeTime, statusLabel } from "../../dashboard/widgets";
  import { showToast } from "../../stores/toast";
  import type { ActivityEntry } from "../../types/application";

  let {
    limit = 5,
    onsettingschange,
  }: { limit?: number; onsettingschange?: (settings: { limit: number }) => void } = $props();

  let entries = $state<ActivityEntry[]>([]);
  let loaded = $state(false);
  let requestSeq = 0;

  $effect(() => {
    const requested = limit;
    const seq = ++requestSeq;
    getRecentActivity(requested)
      .then((result) => {
        if (seq !== requestSeq) return;
        entries = result;
        loaded = true;
      })
      .catch(() => {
        if (seq !== requestSeq) return;
        entries = [];
        loaded = true;
        showToast("Couldn't load recent activity.");
      });
  });

  function describe(e: ActivityEntry): string {
    if (e.oldStatus === null) return `Added ${e.company} — ${e.roleTitle} (${statusLabel(e.newStatus)})`;
    return `Moved ${e.company} to ${statusLabel(e.newStatus)}`;
  }

  function onChange(event: Event) {
    onsettingschange?.({ limit: Number((event.currentTarget as HTMLSelectElement).value) });
  }
</script>

<div class="widget">
  <label class="setting">
    Show
    <select value={String(limit)} onchange={onChange} aria-label="Items to show">
      <option value="3">3</option>
      <option value="5">5</option>
      <option value="10">10</option>
    </select>
  </label>
  {#if loaded && entries.length === 0}
    <p class="empty">No recent activity.</p>
  {:else}
    <ul>
      {#each entries as e, i (`${e.applicationId}-${e.changedAt}-${i}`)}
        <li>{describe(e)} <time datetime={e.changedAt}>{relativeTime(e.changedAt)}</time></li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .setting { font-size: 0.75rem; display: block; text-align: right; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { padding: 0.25rem 0; font-size: 0.85rem; }
  time { color: #666; font-size: 0.75rem; margin-left: 0.25rem; }
  .empty { color: #666; font-size: 0.85rem; }
</style>
