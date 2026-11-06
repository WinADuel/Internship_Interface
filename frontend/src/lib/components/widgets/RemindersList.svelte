<script lang="ts">
  import { applications } from "../../stores/applications";
  import { overdueFollowUps, parseLocalDate, reminderTime, upcomingReminders } from "../../dashboard/widgets";

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

  const overdue = $derived(
    overdueFollowUps($applications, now).map((app) => ({
      app,
      when: parseLocalDate(app.followUpDate as string)?.getTime() as number,
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
  {#if overdue.length > 0}
    <h3 class="overdue-heading">Overdue</h3>
    <ul class="overdue">
      {#each overdue as { app, when } (app.id)}
        <li>Follow up: {app.company} — {app.roleTitle} <time>{format(when)}</time></li>
      {/each}
    </ul>
    <h3>Upcoming</h3>
  {/if}
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
  .setting { display: flex; align-items: center; justify-content: flex-end; gap: 0.4rem; font-size: 0.75rem; color: var(--muted-foreground); margin-bottom: 0.4rem; }
  .setting select { font-size: 0.75rem; padding: 0.15rem 0.4rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; padding: 0.55rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; font-weight: 500; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  time { flex: none; padding: 0.05rem 0.45rem; border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--foreground); font-size: 0.72rem; font-weight: 500; white-space: nowrap; }
  h3 { font-size: 0.72rem; font-weight: 600; margin: 0.5rem 0 0.25rem; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: 0.05em; }
  .overdue-heading { color: var(--destructive); margin-top: 0; }
  .overdue time { color: var(--destructive); border-color: color-mix(in oklch, var(--destructive) 35%, transparent); }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0; }
</style>
