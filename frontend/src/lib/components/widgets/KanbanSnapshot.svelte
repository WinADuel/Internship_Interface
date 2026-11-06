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
  // Bars are drawn against the fullest column.
  const max = $derived(Math.max(1, ...statuses.map((s) => counts[s])));

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
      <li>
        <span class="name">{statusLabel(status)}</span>
        <strong>{counts[status]}</strong>
        <span class="bar" aria-hidden="true"><span style:width="{(counts[status] / max) * 100}%"></span></span>
      </li>
    {/each}
  </ul>
</div>

<style>
  .setting { display: flex; align-items: center; justify-content: flex-end; gap: 0.4rem; font-size: 0.75rem; color: var(--muted-foreground); margin-bottom: 0.5rem; }
  .setting select { font-size: 0.75rem; padding: 0.15rem 0.4rem; }
  ul { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(5.5rem, 1fr)); gap: 0.9rem 1rem; }
  li { display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; }
  .name { font-size: 0.78rem; color: var(--muted-foreground); }
  strong { font-size: 1.35rem; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .bar { display: block; height: 6px; border-radius: 999px; background: var(--muted); overflow: hidden; }
  .bar > span { display: block; height: 100%; border-radius: inherit; background: var(--primary); }
</style>
