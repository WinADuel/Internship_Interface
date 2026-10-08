<script lang="ts">
  /**
   * A list of short text entries edited as chips: type and press Enter (or Add),
   * remove with each chip's ×. Entries are trimmed and de-duplicated ignoring
   * case, like the backend's settings validation, and capped in count and length.
   */
  let {
    label,
    items = $bindable([]),
    hint = "",
    placeholder = "",
    suggestions = [],
    maxItems = 30,
    maxLength = 100,
    validate,
    error = null,
    onchange,
  }: {
    label: string;
    items?: string[];
    hint?: string;
    placeholder?: string;
    suggestions?: string[];
    maxItems?: number;
    maxLength?: number;
    validate?: (value: string) => string | null;
    error?: string | null;
    onchange?: (items: string[]) => void;
  } = $props();

  const id = $props.id();
  let draft = $state("");
  let note = $state<string | null>(null);

  const has = (value: string) => items.some((item) => item.toLowerCase() === value.toLowerCase());
  const offered = $derived(suggestions.filter((s) => !has(s)));

  function set(next: string[]) {
    items = next;
    onchange?.(next);
  }

  /** Adds one entry; returns why it was refused, or null. */
  function tryAdd(raw: string): string | null {
    const value = raw.trim();
    if (!value) return null;
    if (has(value)) return `“${value}” is already in the list.`;
    if (value.length > maxLength) return `Each entry can be at most ${maxLength} characters.`;
    if (items.length >= maxItems) return `At most ${maxItems} entries.`;
    const problem = validate?.(value) ?? null;
    if (problem) return problem;
    set([...items, value]);
    return null;
  }

  function addDraft() {
    note = tryAdd(draft);
    if (note === null) draft = "";
  }

  /**
   * Adds whatever is typed but not yet added, with the same checks as Add (a
   * form calls this before saving). Text already in the list just clears, as
   * nothing is lost. Returns false, showing why, if the text was refused.
   */
  export function commitDraft(): boolean {
    if (draft.trim() && has(draft.trim())) {
      draft = "";
      note = null;
      return true;
    }
    addDraft();
    return note === null;
  }

  function onkeydown(event: KeyboardEvent) {
    if (event.key !== "Enter") return;
    event.preventDefault(); // never submit the surrounding form
    addDraft();
  }

  function remove(index: number) {
    note = null;
    set(items.filter((_, i) => i !== index));
  }
</script>

<div class="chips-field">
  <label for="{id}-input">{label}</label>
  {#if hint}
    <p class="hint" id="{id}-hint">{hint}</p>
  {/if}
  {#if items.length}
    <ul class="chips">
      {#each items as item, i (i)}
        <li>
          <span>{item}</span>
          <button type="button" aria-label={`Remove ${item} from ${label}`} onclick={() => remove(i)}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
  <div class="entry">
    <input
      id="{id}-input"
      {placeholder}
      maxlength={maxLength}
      aria-invalid={error ? "true" : undefined}
      aria-describedby={[hint && `${id}-hint`, (note || error) && `${id}-note`].filter(Boolean).join(" ") || undefined}
      bind:value={draft}
      oninput={() => (note = null)}
      {onkeydown}
    />
    <button type="button" aria-label={`Add to ${label}`} onclick={addDraft}>Add</button>
  </div>
  {#if offered.length}
    <div class="suggestions">
      <span class="hint">Suggestions:</span>
      {#each offered as suggestion (suggestion)}
        <button type="button" class="suggestion" aria-label={`Add ${suggestion} to ${label}`} onclick={() => (note = tryAdd(suggestion))}>
          + {suggestion}
        </button>
      {/each}
    </div>
  {/if}
  {#if note || error}
    <p class="note" id="{id}-note">{note ?? error}</p>
  {/if}
</div>

<style>
  .chips-field { display: flex; flex-direction: column; gap: 0.3rem; }
  label { font-weight: 600; }
  .hint { margin: 0; color: #555; font-size: 0.85rem; }
  .chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .chips li { display: inline-flex; align-items: center; gap: 0.2rem; padding: 0.1rem 0.2rem 0.1rem 0.55rem; border-radius: 999px; background: #eef2f7; max-width: 100%; }
  .chips span { overflow-wrap: anywhere; }
  .chips button { border: 0; background: none; cursor: pointer; font: inherit; padding: 0 0.3rem; line-height: 1; }
  .entry { display: flex; gap: 0.4rem; }
  .entry input { flex: 1 1 auto; min-width: 0; font: inherit; }
  .suggestions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; }
  .suggestion { font: inherit; font-size: 0.85rem; border: 1px dashed #99a; background: none; border-radius: 999px; padding: 0.05rem 0.5rem; cursor: pointer; }
  .note { margin: 0; color: #b3261e; font-size: 0.85rem; overflow-wrap: anywhere; }
</style>
