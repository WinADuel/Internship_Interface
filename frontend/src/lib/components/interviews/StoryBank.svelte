<script lang="ts">
  import { onMount } from "svelte";
  import { listStories, updateStory } from "../../api/stories";
  import { showToast } from "../../stores/toast";
  import type { Story } from "../../types/interview";
  import StoryForm from "./StoryForm.svelte";

  let stories = $state<Story[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let showArchived = $state(false);
  let tag = $state("");
  let adding = $state(false);
  let editingId = $state<number | null>(null);
  let busyId = $state<number | null>(null);

  async function load() {
    try {
      stories = await listStories({ includeArchived: showArchived });
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  function onShowArchived(event: Event) {
    showArchived = (event.currentTarget as HTMLInputElement).checked;
    void load();
  }

  onMount(() => {
    void load();
  });

  const allTags = $derived([...new Set(stories.flatMap((s) => s.tags))].sort());
  const shown = $derived(tag ? stories.filter((s) => s.tags.includes(tag)) : stories);

  function onSaved(saved: Story) {
    stories = stories.some((s) => s.id === saved.id)
      ? stories.map((s) => (s.id === saved.id ? saved : s))
      : [...stories, saved].sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
    adding = false;
    editingId = null;
    showToast("Story saved.", "info");
  }

  async function setArchived(story: Story, archived: boolean) {
    busyId = story.id;
    try {
      const saved = await updateStory(story.id, { archived });
      stories = archived && !showArchived ? stories.filter((s) => s.id !== story.id) : stories.map((s) => (s.id === saved.id ? saved : s));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't update the story.");
    } finally {
      busyId = null;
    }
  }

  const STAR: Array<["situation" | "task" | "action" | "result", string]> = [
    ["situation", "Situation"],
    ["task", "Task"],
    ["action", "Action"],
    ["result", "Result"],
  ];
</script>

<section class="story-bank" aria-label="Story bank">
  <p class="intro">Stories in STAR form (situation, task, action, result) you can reuse across interviews.</p>
  <div class="toolbar">
    <button type="button" onclick={() => { adding = true; editingId = null; }} disabled={adding}>Add story</button>
    <label>
      Tag
      <select bind:value={tag}>
        <option value="">All tags</option>
        {#each allTags as t (t)}<option value={t}>{t}</option>{/each}
      </select>
    </label>
    <label class="check"><input type="checkbox" checked={showArchived} onchange={onShowArchived} /> Show archived</label>
  </div>

  {#if adding}
    <StoryForm onsaved={onSaved} oncancel={() => (adding = false)} />
  {/if}

  {#if failed}
    <p class="empty">Couldn't load your stories.</p>
    <button type="button" onclick={load}>Retry</button>
  {:else if loaded && stories.length === 0}
    <p class="empty">No stories yet. Add one you could tell in any interview.</p>
  {:else if loaded && shown.length === 0}
    <p class="empty">No stories tagged “{tag}”.</p>
  {:else}
    <ul class="stories">
      {#each shown as story (story.id)}
        <li class:archived={story.archived}>
          {#if editingId === story.id}
            <StoryForm {story} onsaved={onSaved} oncancel={() => (editingId = null)} />
          {:else}
            <details>
              <summary>
                <span class="title">{story.title}</span>
                {#if story.archived}<span class="tag muted">archived</span>{/if}
                {#each story.tags as t (t)}<span class="tag">{t}</span>{/each}
              </summary>
              <dl>
                {#each STAR as [key, name] (key)}
                  {#if story[key]}<dt>{name}</dt><dd>{story[key]}</dd>{/if}
                {/each}
              </dl>
              <div class="actions">
                <button type="button" onclick={() => { editingId = story.id; adding = false; }}>Edit</button>
                {#if story.archived}
                  <button type="button" disabled={busyId === story.id} onclick={() => setArchived(story, false)}>Restore</button>
                {:else}
                  <button type="button" disabled={busyId === story.id} onclick={() => setArchived(story, true)}>Archive</button>
                {/if}
              </div>
            </details>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .intro { color: #555; font-size: 0.9rem; margin: 0 0 0.5rem; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1rem; margin-bottom: 0.75rem; }
  .toolbar label { font-size: 0.85rem; display: flex; align-items: center; gap: 0.3rem; }
  select { max-width: 12rem; font: inherit; }
  .story-bank > :global(.story-form) { margin-bottom: 0.75rem; }
  .stories { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .stories > li { border: 1px solid #ddd; border-radius: 6px; padding: 0.5rem 0.6rem; }
  .archived { opacity: 0.7; }
  summary { cursor: pointer; overflow-wrap: anywhere; }
  .title { font-weight: 600; margin-right: 0.3rem; }
  .tag { display: inline-block; font-size: 0.75rem; padding: 0 0.45rem; margin: 0.1rem 0.2rem 0 0; border-radius: 999px; background: #eef2f7; }
  .muted { background: #eee; color: #666; }
  dl { margin: 0.5rem 0; }
  dt { font-weight: 600; font-size: 0.85rem; margin-top: 0.3rem; }
  dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  .actions { display: flex; gap: 0.5rem; }
  .empty { color: #666; font-size: 0.9rem; }
</style>
