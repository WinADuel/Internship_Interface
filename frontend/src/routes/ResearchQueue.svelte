<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../lib/api/client";
  import { addQueueItem, listQueue } from "../lib/api/researchQueue";
  import { formatDateTime } from "../lib/format";
  import { showToast } from "../lib/stores/toast";
  import type { QueueItem, QueueKind, QueueState } from "../lib/types/contact";

  let items = $state<QueueItem[]>([]);
  let mode = $state<"professor_person" | "professor_search">("professor_person");
  let requestText = $state("");
  let targetCount = $state(3);
  let saving = $state(false);

  const KIND_LABELS: Record<QueueKind, string> = {
    professor_person: "Specific professor",
    professor_search: "Search brief",
    company_contacts: "Company contacts",
  };
  const GROUPS: Array<[QueueState, string]> = [
    ["pending", "Pending"],
    ["done", "Done"],
    ["failed", "Failed"],
  ];

  async function load() {
    try {
      items = await listQueue();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't load the research queue.");
    }
  }

  onMount(() => {
    void load();
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    try {
      const created = await addQueueItem({
        kind: mode,
        requestText: requestText.trim(),
        targetCount: mode === "professor_search" ? targetCount : 1,
      });
      items = [created, ...items];
      requestText = "";
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't add the request.");
    } finally {
      saving = false;
    }
  }
</script>

<h1>Research Queue</h1>
<p class="muted">Requests are picked up by the daily Claude job, which researches each one and drafts the emails.</p>

<form onsubmit={submit}>
  <div class="modes" role="group" aria-label="Request type">
    <button type="button" aria-pressed={mode === "professor_person"} onclick={() => (mode = "professor_person")}>
      A specific professor
    </button>
    <button type="button" aria-pressed={mode === "professor_search"} onclick={() => (mode = "professor_search")}>
      Search brief
    </button>
  </div>
  <label>
    {mode === "professor_person" ? "Professor (name and university)" : "What to look for"}
    <textarea required maxlength="1000" rows="2" bind:value={requestText}></textarea>
  </label>
  {#if mode === "professor_search"}
    <label class="inline">
      How many
      <input type="number" min="1" max="10" bind:value={targetCount} />
    </label>
  {/if}
  <button type="submit" disabled={saving}>Add to queue</button>
</form>

{#each GROUPS as [state, label] (state)}
  {@const group = items.filter((i) => i.state === state)}
  <section aria-label={label}>
    <h2>{label} ({group.length})</h2>
    {#if group.length === 0}
      <p class="muted">Nothing here.</p>
    {:else}
      <ul>
        {#each group as item (item.id)}
          <li>
            <span class="text">{item.requestText}</span>
            <span class="meta">{KIND_LABELS[item.kind]} · {formatDateTime(item.createdAt)}</span>
            {#if item.resultNote}<span class="note">{item.resultNote}</span>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{/each}

<style>
  .muted { color: #555; }
  form { display: flex; flex-direction: column; gap: 0.5rem; max-width: 36rem; margin-bottom: 1rem; }
  .modes { display: flex; gap: 0.4rem; }
  .modes button[aria-pressed="true"] { background: #1a5fb4; color: #fff; }
  label { display: flex; flex-direction: column; gap: 0.15rem; }
  .inline { flex-direction: row; align-items: center; gap: 0.5rem; }
  textarea { font: inherit; }
  ul { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  li { display: flex; flex-direction: column; padding: 0.5rem; border: 1px solid #ddd; border-radius: 6px; }
  .text, .note { white-space: pre-wrap; word-break: break-word; }
  .meta { font-size: 0.8rem; color: #666; }
  .note { font-size: 0.85rem; background: #f4f4f6; padding: 0.3rem; border-radius: 4px; margin-top: 0.2rem; }
</style>
