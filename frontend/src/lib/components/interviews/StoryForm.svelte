<script lang="ts">
  import { createStory, updateStory } from "../../api/stories";
  import { showToast } from "../../stores/toast";
  import type { Story, StoryInput } from "../../types/interview";
  import ChipInput from "../ChipInput.svelte";

  /** Pass a story to edit it; omit to add one to the bank. */
  let {
    story = null,
    onsaved,
    oncancel,
  }: { story?: Story | null; onsaved?: (story: Story) => void; oncancel?: () => void } = $props();

  // Seeded once; the parent re-mounts the form to edit a different story.
  /* svelte-ignore state_referenced_locally */
  const initial = story;

  const TAG_SUGGESTIONS = ["leadership", "teamwork", "conflict", "failure", "ownership", "technical"];

  let title = $state(initial?.title ?? "");
  let situation = $state(initial?.situation ?? "");
  let task = $state(initial?.task ?? "");
  let action = $state(initial?.action ?? "");
  let result = $state(initial?.result ?? "");
  let tags = $state<string[]>([...(initial?.tags ?? [])]);
  let error = $state("");
  let saving = $state(false);
  let chips: { commitDraft: () => boolean } | undefined = $state();

  const orNull = (value: string): string | null => value.trim() || null;

  async function submit(event: Event) {
    event.preventDefault();
    if (saving) return;
    error = "";
    if (!title.trim()) {
      error = "Give the story a title.";
      return;
    }
    if (chips && !chips.commitDraft()) return;
    const input: StoryInput = {
      title: title.trim(),
      situation: orNull(situation),
      task: orNull(task),
      action: orNull(action),
      result: orNull(result),
      tags: $state.snapshot(tags),
    };
    saving = true;
    try {
      const saved = initial ? await updateStory(initial.id, input) : await createStory(input);
      onsaved?.(saved);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't save the story.");
    } finally {
      saving = false;
    }
  }
</script>

<form class="story-form" aria-label={initial ? "Edit story" : "New story"} novalidate onsubmit={submit}>
  <label>Title <input bind:value={title} maxlength="200" autocomplete="off" /></label>
  <label>Situation <textarea rows="2" bind:value={situation} maxlength="5000"></textarea></label>
  <label>Task <textarea rows="2" bind:value={task} maxlength="5000"></textarea></label>
  <label>Action <textarea rows="3" bind:value={action} maxlength="5000"></textarea></label>
  <label>Result <textarea rows="2" bind:value={result} maxlength="5000"></textarea></label>
  <ChipInput bind:this={chips} label="Tags" bind:items={tags} suggestions={TAG_SUGGESTIONS} maxItems={15} maxLength={40} />
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <div class="actions">
    <button type="submit" disabled={saving}>{initial ? "Save story" : "Add story"}</button>
    <button type="button" onclick={() => oncancel?.()}>Cancel</button>
  </div>
</form>

<style>
  .story-form { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; }
  label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; font-weight: 600; }
  input, textarea { font: inherit; font-weight: 400; padding: 0.35rem; min-width: 0; }
  .actions { display: flex; gap: 0.5rem; }
  .error { color: #b3261e; margin: 0; }
</style>
