<script lang="ts">
  import { applications } from "../../stores/applications";
  import { parseLocalDate, reminderTime, upcomingReminders } from "../../dashboard/widgets";

  let {
    withinDays = 14,
    onsettingschange,
  }: { withinDays?: number; onsettingschange?: (settings: { withinDays: number }) => void } = $props();

  const now = $derived(new Date());
  const items = $derived(
    upcomingReminders($applications, withinDays, now).map((app) => ({
      app,
      when: reminderTime(app, withinDays, now) as number,
    })),
  );

  function format(ms: number): string {
    return new Date(ms).toLocaleDateString(undefined, { dateStyle: "medium" });
  }

  function kind(app: { followUpDate: string | null }, when: number): string {
    if (app.followUpDate && parseLocalDate(app.followUpDate)?.getTime() === when) return "Follow up";
    return "Interview";
  }

  function onChange(event: Event) {
    onsettingschange?.({ withinDays: Number((event.currentTarget as HTMLSelectElement).value) });
  }
</script>

<div class="widget">
  <label class="setting">
    Within
    <select value={String(withinDays)} onchange={onChange} aria-label="Days ahead">
      <option value="7">7 days</option>
      <option value="14">14 days</option>
      <option value="30">30 days</option>
    </select>
  </label>
  {#if items.length === 0}
    <p class="empty">No upcoming reminders.</p>
  {:else}
    <ul>
      {#each items as { app, when } (app.id)}
        <li>{kind(app, when)}: {app.company} — {app.roleTitle} <time>{format(when)}</time></li>
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
