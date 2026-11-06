<script lang="ts">
  import { getRecentActivity } from "../../api/applications";
  import { getContactActivity } from "../../api/contacts";
  import { statusLabel as contactStatusLabel } from "../../contacts/actions";
  import { mergeActivity, type FeedItem } from "../../dashboard/activity";
  import { relativeTime, statusLabel } from "../../dashboard/widgets";
  import { showToast } from "../../stores/toast";
  import type { ApplicationStatus } from "../../types/application";
  import type { ContactStatus } from "../../types/contact";

  let {
    limit = 5,
    onsettingschange,
  }: { limit?: number; onsettingschange?: (settings: { limit: number }) => void } = $props();

  let entries = $state<FeedItem[]>([]);
  let loaded = $state(false);
  let requestSeq = 0;

  $effect(() => {
    const requested = limit;
    const seq = ++requestSeq;
    // Either feed may fail on its own; show whatever arrived.
    Promise.allSettled([getRecentActivity(requested), getContactActivity(requested)]).then(([apps, people]) => {
      if (seq !== requestSeq) return;
      entries = mergeActivity(
        apps.status === "fulfilled" ? apps.value : [],
        people.status === "fulfilled" ? people.value : [],
        requested,
      );
      loaded = true;
      if (apps.status === "rejected" || people.status === "rejected") showToast("Couldn't load recent activity.");
    });
  });

  function describe(e: FeedItem): string {
    if (e.kind === "contact") {
      return `${e.label}: ${contactStatusLabel(e.newStatus as ContactStatus, e.contactKind ?? "professor")}`;
    }
    const status = statusLabel(e.newStatus as ApplicationStatus);
    if (e.oldStatus === null) return `Added ${e.label} (${status})`;
    return `Moved ${e.label} to ${status}`;
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
      {#each entries as e, i (`${e.kind}-${e.changedAt}-${i}`)}
        <li>{describe(e)} <time datetime={e.changedAt}>{relativeTime(e.changedAt)}</time></li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .setting { display: flex; align-items: center; justify-content: flex-end; gap: 0.4rem; font-size: 0.75rem; color: var(--muted-foreground); margin-bottom: 0.4rem; }
  .setting select { font-size: 0.75rem; padding: 0.15rem 0.4rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; padding: 0.55rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; font-weight: 500; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  time { flex: none; color: var(--muted-foreground); font-size: 0.75rem; font-weight: 400; font-variant-numeric: tabular-nums; }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0; }
</style>
