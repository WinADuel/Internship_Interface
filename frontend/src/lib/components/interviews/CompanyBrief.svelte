<script lang="ts">
  import { onMount } from "svelte";
  import { getBrief, requestBrief } from "../../api/interviews";
  import { listQueue } from "../../api/researchQueue";
  import { isSafeHttpUrl } from "../../contacts/links";
  import { formatDateTime } from "../../format";
  import { showToast } from "../../stores/toast";
  import type { PrepBrief } from "../../types/interview";

  let { applicationId }: { applicationId: number } = $props();

  let brief = $state<PrepBrief | null>(null);
  let loaded = $state(false);
  let failed = $state(false);
  let pending = $state(false);
  let requesting = $state(false);

  onMount(() => {
    getBrief(applicationId).then(
      (b) => {
        brief = b;
        loaded = true;
      },
      () => {
        failed = true;
        loaded = true;
      },
    );
    // A request still waiting for the daily run shows as such after a reload.
    listQueue("pending").then(
      (items) => {
        if (items.some((i) => i.kind === "interview_brief" && i.applicationId === applicationId)) pending = true;
      },
      () => {},
    );
  });

  async function request() {
    requesting = true;
    try {
      await requestBrief(applicationId);
      pending = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't request a brief.");
    } finally {
      requesting = false;
    }
  }
</script>

<!-- Written by the Claude routine from web sources: untrusted, so plain text only and http(s) links only. -->
<section aria-labelledby="brief-heading">
  <h2 id="brief-heading">Company brief</h2>
  {#if failed}
    <p class="empty">Couldn't load the company brief.</p>
  {:else if loaded && brief}
    <p class="meta">Written by Claude from public sources, {formatDateTime(brief.updatedAt)}. Check anything important.</p>
    <div class="body">{brief.body}</div>
    {#if brief.sources.length}
      <h3>Sources</h3>
      <ul class="sources">
        {#each brief.sources as source, i (i)}
          <li>
            {#if isSafeHttpUrl(source.url)}
              <a href={source.url} target="_blank" rel="noopener noreferrer">{source.label || source.url}</a>
            {:else}
              <span>{source.label || source.url}</span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {:else if loaded}
    <p class="empty">No brief yet. The daily Claude run can research the company for you.</p>
  {/if}
  {#if pending}
    <p class="pending" role="status">Requested — the daily run picks it up.</p>
  {:else if loaded}
    <button type="button" disabled={requesting} onclick={request}>
      {brief ? "Ask Claude for a fresh brief" : "Ask Claude for a brief"}
    </button>
  {/if}
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  h3 { font-size: 0.9rem; margin: 0.6rem 0 0.2rem; }
  .meta { font-size: 0.8rem; color: #666; margin: 0 0 0.4rem; }
  .body { white-space: pre-wrap; overflow-wrap: anywhere; }
  .sources { margin: 0 0 0.5rem; padding-left: 1.2rem; overflow-wrap: anywhere; font-size: 0.9rem; }
  .pending { padding: 0.4rem; background: #fff3c4; border-radius: 6px; font-size: 0.9rem; }
  .empty { color: #666; font-size: 0.9rem; }
</style>
