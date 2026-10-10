<script lang="ts">
  import { onDestroy } from "svelte";
  import { ApiError } from "../../api/client";

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
  let status = $state<"idle" | "pending" | "saving" | "saved" | "error" | "missing">("idle");
  let timer: ReturnType<typeof setTimeout> | undefined;
  // One save loop at a time; a flush while it runs leaves the newer text to it.
  let looping = false;

  function schedule() {
    status = "pending";
    clearTimeout(timer);
    timer = setTimeout(() => void flush(), SAVE_DELAY_MS);
  }

  async function flush(): Promise<void> {
    clearTimeout(timer);
    timer = undefined;
    if (looping) return;
    looping = true;
    try {
      // Text typed during a save goes out as soon as that save is back.
      while (text !== saved) {
        const sending = text;
        status = "saving";
        try {
          await save(sending.trim() ? sending : null);
        } catch (err) {
          status = err instanceof ApiError && err.status === 404 ? "missing" : "error";
          return;
        }
        saved = sending;
      }
      if (status === "saving" || status === "pending") status = timer === undefined ? "saved" : "pending";
    } finally {
      looping = false;
    }
  }

  onDestroy(() => {
    clearTimeout(timer);
    timer = undefined;
    // A running loop saves the newest text itself once its save is back.
    if (!looping && text !== saved) void flush();
  });

  const STATUS_TEXT = {
    idle: "",
    pending: "Unsaved changes…",
    saving: "Saving…",
    saved: "Saved",
    error: "Couldn't save. Keep typing to try again.",
    missing: "This round no longer exists.",
  };
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
  <span class="status" class:error={status === "error" || status === "missing"} id="{id}-status" role="status">{STATUS_TEXT[status]}</span>
</div>

<style>
  .autosave { display: flex; flex-direction: column; gap: 0.2rem; }
  label { font-weight: 600; font-size: 0.9rem; }
  textarea { font: inherit; padding: 0.4rem; width: 100%; box-sizing: border-box; resize: vertical; }
  .status { font-size: 0.75rem; color: #666; min-height: 1em; }
  .error { color: #b3261e; }
</style>
