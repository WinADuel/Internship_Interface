<script lang="ts">
  import { onMount } from "svelte";
  import { listRounds } from "../../api/interviews";
  import { countdown, formatRoundTime, roundName, sortByDate } from "../../interviews/format";
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

  const now = $derived(new Date());
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
  li { padding: 0.25rem 0; font-size: 0.85rem; overflow-wrap: anywhere; display: flex; flex-wrap: wrap; gap: 0 0.4rem; }
  .round { color: #333; }
  .when, .progress { color: #666; font-size: 0.75rem; }
  h3 { font-size: 0.8rem; margin: 0.5rem 0 0.2rem; text-transform: uppercase; letter-spacing: 0.03em; }
  .due-heading { color: #8a4b00; margin-top: 0; }
  .empty { color: #666; font-size: 0.85rem; }
  button { font-size: 0.8rem; padding: 0.2rem 0.5rem; }
</style>
