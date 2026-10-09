<script lang="ts">
  import type { ChecklistItem } from "../../types/interview";

  /** `onchange` gets the whole new list; items added here have an empty id until the server assigns one. */
  let {
    items,
    onchange,
  }: { items: ChecklistItem[]; onchange: (next: ChecklistItem[]) => void } = $props();

  const MAX_ITEMS = 30;
  const MAX_LABEL = 200;

  let draft = $state("");
  let note = $state("");

  const done = $derived(items.filter((i) => i.done).length);

  function toggle(index: number) {
    onchange(items.map((item, i) => (i === index ? { ...item, done: !item.done } : item)));
  }

  function remove(index: number) {
    onchange(items.filter((_, i) => i !== index));
  }

  function add(event: Event) {
    event.preventDefault();
    const label = draft.trim();
    note = "";
    if (!label) return;
    if (items.length >= MAX_ITEMS) {
      note = `At most ${MAX_ITEMS} items.`;
      return;
    }
    onchange([...items, { id: "", label: label.slice(0, MAX_LABEL), done: false }]);
    draft = "";
  }
</script>

<section aria-labelledby="checklist-heading">
  <h2 id="checklist-heading">Checklist <span class="count">{done}/{items.length}</span></h2>
  {#if items.length === 0}
    <p class="empty">Nothing on the checklist.</p>
  {:else}
    <ul>
      {#each items as item, i (item.id || `new-${i}`)}
        <li>
          <label class:done={item.done}>
            <input type="checkbox" checked={item.done} onchange={() => toggle(i)} />
            <span>{item.label}</span>
          </label>
          <button type="button" class="remove" aria-label={`Remove “${item.label}”`} onclick={() => remove(i)}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
  <form class="add" aria-label="Add checklist item" onsubmit={add}>
    <input aria-label="New checklist item" bind:value={draft} maxlength={MAX_LABEL} placeholder="Add an item" />
    <button type="submit">Add</button>
  </form>
  {#if note}<p class="note" role="alert">{note}</p>{/if}
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  .count { font-weight: 400; color: #555; font-size: 0.9rem; }
  ul { list-style: none; margin: 0 0 0.5rem; padding: 0; display: flex; flex-direction: column; gap: 0.2rem; }
  li { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
  label { display: flex; gap: 0.4rem; align-items: flex-start; overflow-wrap: anywhere; min-width: 0; }
  .done span { color: #666; text-decoration: line-through; }
  .remove { border: 0; background: none; cursor: pointer; font: inherit; padding: 0 0.3rem; color: #666; }
  .add { display: flex; gap: 0.4rem; }
  .add input { flex: 1 1 auto; min-width: 0; font: inherit; padding: 0.3rem; }
  .empty { color: #666; font-size: 0.9rem; }
  .note { color: #b3261e; font-size: 0.85rem; margin: 0.3rem 0 0; }
</style>
