<script lang="ts">
  import { onMount, tick } from "svelte";
  import { push } from "svelte-spa-router";
  import RoundForm from "../lib/components/interviews/RoundForm.svelte";
  import RoundList from "../lib/components/interviews/RoundList.svelte";
  import StoryBank from "../lib/components/interviews/StoryBank.svelte";
  import { applications, loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";
  import type { InterviewRoundDetail } from "../lib/types/interview";

  type Tab = "upcoming" | "past" | "stories";

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: "upcoming", label: "Upcoming" },
    { id: "past", label: "Past" },
    { id: "stories", label: "Story bank" },
  ];

  let tab = $state<Tab>("upcoming");
  let adding = $state(false);
  let tabButtons: HTMLButtonElement[] = $state([]);

  onMount(() => {
    loadApplications().catch(() => showToast("Couldn't load applications."));
  });

  async function onTabKeydown(event: KeyboardEvent, index: number) {
    const last = TABS.length - 1;
    const target =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (target === null) return;
    event.preventDefault();
    tab = TABS[target].id;
    await tick();
    tabButtons[target]?.focus();
  }

  function onAdded(round: InterviewRoundDetail) {
    adding = false;
    void push(`/interviews/${round.id}`);
  }
</script>

<div class="header">
  <h1>Interview Prep</h1>
  {#if tab !== "stories"}
    <button type="button" onclick={() => (adding = true)} disabled={adding}>Add round</button>
  {/if}
</div>

{#if adding && tab !== "stories"}
  <RoundForm applications={$applications} onsaved={onAdded} oncancel={() => (adding = false)} />
{/if}

<div class="tabs" role="tablist" aria-label="Interview Prep">
  {#each TABS as t, i (t.id)}
    <button
      type="button"
      role="tab"
      id="interviews-tab-{t.id}"
      aria-selected={tab === t.id}
      aria-controls="interviews-panel"
      tabindex={tab === t.id ? 0 : -1}
      bind:this={tabButtons[i]}
      onclick={() => (tab = t.id)}
      onkeydown={(event) => onTabKeydown(event, i)}
    >
      {t.label}
    </button>
  {/each}
</div>

<div class="panel" role="tabpanel" id="interviews-panel" aria-labelledby="interviews-tab-{tab}">
  {#if tab === "stories"}
    <StoryBank />
  {:else}
    {#key tab}
      <RoundList scope={tab} />
    {/key}
  {/if}
</div>

<style>
  .header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .header button { white-space: nowrap; }
  .tabs { display: flex; flex-wrap: wrap; gap: 0.25rem; border-bottom: 1px solid #ddd; margin: 0.75rem 0; }
  .tabs button { border: 1px solid transparent; border-bottom: 0; background: none; padding: 0.4rem 0.9rem; border-radius: 6px 6px 0 0; cursor: pointer; font: inherit; }
  .tabs button[aria-selected="true"] { border-color: #ddd; background: #fff; font-weight: 600; margin-bottom: -1px; }
  .tabs button:focus-visible { outline: 2px solid #1a5fb4; }
</style>
