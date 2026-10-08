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
  .setting { font-size: 0.75rem; display: block; text-align: right; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { padding: 0.25rem 0; font-size: 0.85rem; }
  time { color: #666; font-size: 0.75rem; margin-left: 0.25rem; }
  .empty { color: #666; font-size: 0.85rem; }
</style>
