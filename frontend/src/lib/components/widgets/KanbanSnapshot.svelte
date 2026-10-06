<script lang="ts">
  import { applications } from "../../stores/applications";
  import { countByStatus, statusLabel } from "../../dashboard/widgets";
  import type { ApplicationStatus } from "../../types/application";

  let {
    hideEmpty = false,
    onsettingschange,
  }: { hideEmpty?: boolean; onsettingschange?: (settings: { hideEmpty: boolean }) => void } = $props();

  const statuses: ApplicationStatus[] = ["wishlist", "applied", "phone_screen", "interview", "offer", "rejected"];
  const counts = $derived(countByStatus($applications));
  const visible = $derived(hideEmpty ? statuses.filter((s) => counts[s] > 0) : statuses);

  function onChange(event: Event) {
    onsettingschange?.({ hideEmpty: (event.currentTarget as HTMLSelectElement).value === "true" });
  }
</script>

<div class="widget">
  <label class="setting">
    Columns
    <select value={String(hideEmpty)} onchange={onChange} aria-label="Columns shown">
      <option value="false">All</option>
      <option value="true">Non-empty only</option>
    </select>
  </label>
  <ul>
    {#each visible as status (status)}
      <li><span>{statusLabel(status)}</span> <strong>{counts[status]}</strong></li>
    {/each}
  </ul>
</div>

<style>
  .setting { font-size: 0.75rem; display: block; text-align: right; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; justify-content: space-between; padding: 0.2rem 0; font-size: 0.85rem; }
</style>
