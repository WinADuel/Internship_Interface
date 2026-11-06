<script lang="ts">
  import { onMount } from "svelte";
  import { listRounds } from "../../api/interviews";
  import { countdown, formatRoundTime, roundName, sortByDate } from "../../interviews/format";
  import { clock } from "../../stores/clock";
  import type { InterviewRoundListItem } from "../../types/interview";

  const WITHIN_DAYS = 14;
  const DAY_MS = 86_400_000;

  let rounds = $state<InterviewRoundListItem[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let loading = $state(false);

  async function load() {
    loading = true;
    try {
      rounds = await listRounds({ scope: "all" });
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

  const now = $derived($clock);
  const upcoming = $derived(
    sortByDate(
      rounds.filter((r) => {
        if (r.state !== "scheduled" || !r.scheduledAt) return false;
        const t = new Date(r.scheduledAt).getTime();
        return t >= now.getTime() && t <= now.getTime() + WITHIN_DAYS * DAY_MS;
      }),
    ),
  );
  const thankYous = $derived(sortByDate(rounds.filter((r) => r.thankYouDue)));
</script>

<div class="widget">
  {#if failed}
    <p class="empty">Couldn't load interviews.</p>
    <button type="button" onclick={load} disabled={loading}>Retry</button>
  {:else if loaded && upcoming.length === 0 && thankYous.length === 0}
    <p class="empty">No interviews in the next {WITHIN_DAYS} days. <a href="#/interviews">Interview Prep</a></p>
  {:else if loaded}
    {#if thankYous.length}
      <h3 class="due-heading">Thank-you due</h3>
      <ul>
        {#each thankYous as r (r.id)}
          <li><a href="#/interviews/{r.id}">{r.company} — {roundName(r)}</a></li>
        {/each}
      </ul>
      {#if upcoming.length}<h3>Next {WITHIN_DAYS} days</h3>{/if}
    {/if}
    <ul>
      {#each upcoming as r (r.id)}
        <li>
          <a href="#/interviews/{r.id}">{r.company} — {r.roleTitle}</a>
          <span class="round">{roundName(r)}</span>
          <span class="when">{formatRoundTime(r.scheduledAt as string)} · {countdown(r.scheduledAt as string, now)}</span>
          {#if r.checklistTotal > 0}
            <span class="progress">Checklist {r.checklistDone}/{r.checklistTotal}</span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.1rem 0.5rem; padding: 0.55rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; overflow-wrap: anywhere; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  li a { color: var(--foreground); font-weight: 500; }
  .round { color: var(--muted-foreground); }
  .when { flex-basis: 100%; color: var(--muted-foreground); font-size: 0.78rem; }
  .progress { padding: 0.05rem 0.45rem; border: 1px solid color-mix(in oklch, var(--info) 30%, transparent); border-radius: var(--radius-sm); color: var(--info); font-size: 0.72rem; font-weight: 500; }
  h3 { font-size: 0.72rem; font-weight: 600; margin: 0.5rem 0 0.25rem; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: 0.05em; }
  .due-heading { color: var(--warning); margin-top: 0; }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0 0 0.5rem; }
  button { font-size: 0.8rem; padding: 0.2rem 0.6rem; }
</style>
