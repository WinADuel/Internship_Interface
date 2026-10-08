<script lang="ts">
  import { ApiError } from "../../api/client";
  import { confirmPaste, previewPaste } from "../../api/discovery";
  import { postingLabel, sourceLabel } from "../../discovery/format";
  import { showToast } from "../../stores/toast";
  import type { PastePreview, Posting } from "../../types/discovery";

  let { onsaved }: { onsaved?: (posting: Posting) => void } = $props();

  let url = $state("");
  let preview = $state<PastePreview | null>(null);
  let company = $state("");
  let title = $state("");
  let locations = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);

  function errorText(err: unknown, fallback: string): string {
    return err instanceof ApiError ? err.message : fallback;
  }

  async function read(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      const result = await previewPaste(url.trim());
      preview = result;
      company = result.company;
      title = result.title;
      locations = result.locations.join(", ");
    } catch (err) {
      preview = null;
      error = errorText(err, "Couldn't read that link.");
    } finally {
      busy = false;
    }
  }

  function cancel() {
    preview = null;
    error = null;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!preview) return;
    busy = true;
    error = null;
    try {
      const saved = await confirmPaste({
        url: preview.url,
        company: company.trim(),
        title: title.trim(),
        locations: locations.split(",").map((l) => l.trim()).filter(Boolean),
        datePosted: preview.datePosted,
      });
      preview = null;
      url = "";
      showToast(`Saved ${postingLabel(saved)}.`, "info");
      onsaved?.(saved);
    } catch (err) {
      error = errorText(err, "Couldn't save the posting.");
    } finally {
      busy = false;
    }
  }
</script>

<section class="paste" aria-labelledby="paste-heading">
  <h2 id="paste-heading">Paste a posting link</h2>
  <form class="url" onsubmit={read}>
    <label>
      Posting link
      <input type="url" required maxlength="2000" placeholder="https://…" bind:value={url} />
    </label>
    <button type="submit" disabled={busy}>Preview</button>
  </form>

  {#if preview}
    <!-- Preview text comes from the fetched page: it only ever fills input values. -->
    <form class="fields" onsubmit={save}>
      <p class="muted">Read from <span class="source">{sourceLabel(preview.source)}</span>. Check the details, then save.</p>
      <label>Company <input required maxlength="300" bind:value={company} /></label>
      <label>Title <input required maxlength="300" bind:value={title} /></label>
      <label>Locations (comma-separated) <input bind:value={locations} /></label>
      <div class="buttons">
        <button type="submit" disabled={busy}>Save to Saved</button>
        <button type="button" disabled={busy} onclick={cancel}>Cancel</button>
      </div>
    </form>
  {/if}

  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
</section>

<style>
  .paste { margin-bottom: 1rem; max-width: 40rem; }
  h2 { font-size: 1rem; margin: 0 0 0.4rem; }
  form { display: flex; gap: 0.5rem; }
  .url { flex-wrap: wrap; align-items: flex-end; }
  .url label { flex: 1 1 18rem; }
  .fields { flex-direction: column; margin-top: 0.5rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; }
  label { display: flex; flex-direction: column; gap: 0.15rem; }
  input { font: inherit; min-width: 0; }
  .buttons { display: flex; gap: 0.4rem; }
  .muted { margin: 0; color: #555; font-size: 0.85rem; }
  .source { font-weight: 600; }
  .error { color: #b3261e; margin: 0.4rem 0 0; overflow-wrap: anywhere; }
</style>
