<script lang="ts">
  import { onMount } from "svelte";
  import { setRoundStories } from "../../api/interviews";
  import { listStories } from "../../api/stories";
  import { showToast } from "../../stores/toast";
  import type { InterviewRoundDetail, RoundStory, Story } from "../../types/interview";
  import StoryForm from "./StoryForm.svelte";

  /** `onchanged` gets the round as saved after the linked set changes. */
  let {
    roundId,
    linked,
    onchanged,
  }: { roundId: number; linked: RoundStory[]; onchanged: (round: InterviewRoundDetail) => Promise<void> } = $props();

  let bank = $state<Story[]>([]);
  let writing = $state(false);
  let busy = $state(false);

  onMount(() => {
    listStories().then(
      (rows) => (bank = rows),
      () => showToast("Couldn't load the story bank."),
    );
  });

  const linkedIds = $derived(new Set(linked.map((s) => s.id)));
  const available = $derived(bank.filter((s) => !s.archived && !linkedIds.has(s.id)));
  const byId = $derived(new Map(bank.map((s) => [s.id, s])));

  async function replace(ids: number[]) {
    busy = true;
    try {
      await onchanged(await setRoundStories(roundId, ids));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't update this round's stories.");
    } finally {
      busy = false;
    }
  }

  function onPick(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    const id = Number(select.value);
    select.value = "";
    if (id) void replace([...linked.map((s) => s.id), id]);
  }

  async function onWritten(story: Story) {
    bank = [...bank, story];
    writing = false;
    await replace([...linked.map((s) => s.id), story.id]);
  }

  const STAR = [
    ["situation", "Situation"],
    ["task", "Task"],
    ["action", "Action"],
    ["result", "Result"],
  ] as const;
</script>

<section aria-labelledby="stories-heading">
  <h2 id="stories-heading">Stories for this round</h2>
  {#if linked.length === 0}
    <p class="empty">No stories picked yet. Pick 2–3 you could tell.</p>
  {:else}
    <ul>
      {#each linked as s (s.id)}
        {@const full = byId.get(s.id)}
        <li>
          <details>
            <summary>{s.title}</summary>
            {#if full}
              <dl>
                {#each STAR as [key, name] (key)}
                  {#if full[key]}<dt>{name}</dt><dd>{full[key]}</dd>{/if}
                {/each}
              </dl>
            {/if}
          </details>
          <button type="button" class="remove" aria-label={`Remove story “${s.title}”`} disabled={busy}
            onclick={() => replace(linked.filter((x) => x.id !== s.id).map((x) => x.id))}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
  <div class="row">
    <select aria-label="Add a story from the bank" onchange={onPick} disabled={busy || available.length === 0}>
      <option value="">{available.length ? "Add from the story bank…" : "No other stories in the bank"}</option>
      {#each available as s (s.id)}<option value={s.id}>{s.title}</option>{/each}
    </select>
    <button type="button" onclick={() => (writing = true)} disabled={writing}>Write a new story</button>
  </div>
  {#if writing}
    <StoryForm onsaved={onWritten} oncancel={() => (writing = false)} />
  {/if}
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  ul { list-style: none; margin: 0 0 0.5rem; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
  li { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
  details { min-width: 0; overflow-wrap: anywhere; }
  summary { cursor: pointer; }
  dl { margin: 0.3rem 0 0.3rem 1rem; }
  dt { font-weight: 600; font-size: 0.85rem; }
  dd { margin: 0 0 0.2rem; white-space: pre-wrap; }
  .remove { border: 0; background: none; cursor: pointer; font: inherit; padding: 0 0.3rem; color: #666; }
  .row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.5rem; }
  select { max-width: 100%; min-width: 0; font: inherit; }
  .empty { color: #666; font-size: 0.9rem; }
</style>
