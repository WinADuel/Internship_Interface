<script lang="ts">
  import { onMount } from "svelte";
  import { listRounds } from "../../api/interviews";
  import {
    OUTCOME_LABELS,
    STATE_LABELS,
    countdown,
    formatRoundTime,
    roundName,
    sortByDate,
  } from "../../interviews/format";
  import { clock } from "../../stores/clock";
  import type { InterviewRoundListItem } from "../../types/interview";

  let { scope }: { scope: "upcoming" | "past" } = $props();

  let rounds = $state<InterviewRoundListItem[]>([]);
  let loaded = $state(false);
  let failed = $state(false);

  async function load() {
    try {
      rounds = await listRounds({ scope });
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    void load();
  });

  const now = $derived($clock);
  const sorted = $derived(sortByDate(rounds, scope === "past"));
  const dated = $derived(sorted.filter((r) => r.scheduledAt));
  const undated = $derived(sorted.filter((r) => !r.scheduledAt));
</script>

{#snippet row(r: InterviewRoundListItem)}
  <li>
    <a href="#/interviews/{r.id}">
      <span class="company">{r.company} — {r.roleTitle}</span>
      <span class="round">{roundName(r)}</span>
    </a>
    <div class="meta">
      {#if r.scheduledAt}
        <time datetime={r.scheduledAt}>{formatRoundTime(r.scheduledAt)}</time>
        {#if scope === "upcoming"}<span class="countdown">{countdown(r.scheduledAt, now)}</span>{/if}
      {/if}
      {#if scope === "upcoming"}
        {#if r.checklistTotal > 0}
          <span class="progress" class:complete={r.checklistDone === r.checklistTotal}>
            Checklist {r.checklistDone}/{r.checklistTotal}
          </span>
        {/if}
      {:else}
        <span class="state">{STATE_LABELS[r.state]}</span>
        {#if r.outcome}<span class="outcome">{OUTCOME_LABELS[r.outcome]}</span>{/if}
        {#if r.thankYouDue}<span class="due">Thank-you due</span>{/if}
      {/if}
    </div>
  </li>
{/snippet}

{#if failed}
  <p class="empty">Couldn't load interviews.</p>
  <button type="button" onclick={load}>Retry</button>
{:else if loaded && rounds.length === 0}
  <p class="empty">
    {scope === "upcoming"
      ? "No upcoming interviews. Add a round here or from an application."
      : "No past interviews yet."}
  </p>
{:else if loaded}
  {#if dated.length}
    <ul class="rounds">{#each dated as r (r.id)}{@render row(r)}{/each}</ul>
  {/if}
  {#if undated.length}
    <h3>Not scheduled yet</h3>
    <ul class="rounds">{#each undated as r (r.id)}{@render row(r)}{/each}</ul>
  {/if}
{/if}

<style>
  .rounds { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  li { border: 1px solid #ddd; border-radius: 6px; padding: 0.5rem 0.6rem; overflow-wrap: anywhere; }
  a { display: flex; flex-wrap: wrap; gap: 0 0.5rem; text-decoration: none; }
  .company { font-weight: 600; }
  .round { color: #333; }
  .meta { display: flex; flex-wrap: wrap; gap: 0.2rem 0.75rem; font-size: 0.85rem; color: #555; margin-top: 0.2rem; }
  .countdown { font-weight: 600; color: #1a5fb4; }
  .complete { color: #2b7a0b; }
  .due { color: #8a4b00; font-weight: 600; }
  h3 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.03em; margin: 1rem 0 0.4rem; color: #555; }
  .empty { color: #666; font-size: 0.9rem; }
</style>
