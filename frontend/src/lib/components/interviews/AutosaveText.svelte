<script lang="ts">
  import { onDestroy } from "svelte";

  /**
   * A text area that saves itself: shortly after typing stops, when it loses
   * focus, and when it goes away. Seeded once from `value`; later server
   * copies never replace what the user is typing.
   */
  let {
    label,
    value,
    save,
    rows = 6,
    maxlength,
    placeholder = "",
  }: {
    label: string;
    value: string | null;
    save: (text: string | null) => Promise<void>;
    rows?: number;
    maxlength?: number;
    placeholder?: string;
  } = $props();

  const SAVE_DELAY_MS = 1000;

  const id = $props.id();
  /* svelte-ignore state_referenced_locally */
  let text = $state(value ?? "");
  /* svelte-ignore state_referenced_locally */
  let saved = value ?? "";
  let status = $state<"idle" | "pending" | "saving" | "saved" | "error">("idle");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: Promise<void> | null = null;

  function schedule() {
    status = "pending";
    clearTimeout(timer);
    timer = setTimeout(() => void flush(), SAVE_DELAY_MS);
  }

  async function flush(): Promise<void> {
    clearTimeout(timer);
    timer = undefined;
    if (inFlight) {
      await inFlight; // one save at a time; then save whatever is newer
    }
    if (text === saved) {
      if (status === "pending") status = "saved";
      return;
    }
    const sending = text;
    status = "saving";
    let typedSince = false;
    inFlight = save(sending.trim() ? sending : null).then(
      () => {
        saved = sending;
        typedSince = text !== sending;
        status = typedSince ? "pending" : "saved";
      },
      () => {
        status = "error";
      },
    );
    await inFlight;
    inFlight = null;
    // Text typed during the save normally has its own timer; make sure it is saved.
    if (typedSince && timer === undefined) schedule();
  }

  onDestroy(() => {
    clearTimeout(timer);
    if (text !== saved) void save(text.trim() ? text : null).catch(() => {});
  });

  const STATUS_TEXT = { idle: "", pending: "Unsaved changes…", saving: "Saving…", saved: "Saved", error: "Couldn't save. Keep typing to try again." };
</script>

<div class="autosave">
  <label for="{id}-text">{label}</label>
  <textarea
    id="{id}-text"
    {rows}
    {maxlength}
    {placeholder}
    bind:value={text}
    oninput={schedule}
    onblur={() => void flush()}
    aria-describedby="{id}-status"
  ></textarea>
  <span class="status" class:error={status === "error"} id="{id}-status" role="status">{STATUS_TEXT[status]}</span>
</div>

<style>
  .autosave { display: flex; flex-direction: column; gap: 0.2rem; }
  label { font-weight: 600; font-size: 0.9rem; }
  textarea { font: inherit; padding: 0.4rem; width: 100%; box-sizing: border-box; resize: vertical; }
  .status { font-size: 0.75rem; color: #666; min-height: 1em; }
  .error { color: #b3261e; }
</style>
