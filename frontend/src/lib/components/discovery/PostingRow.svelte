<script lang="ts" module>
  export type PostingAction = "save" | "dismiss" | "apply" | "remove" | "restore";
</script>

<script lang="ts">
  import {
    isWebUrl,
    postingWhen,
    postingLabel,
    shortLocations,
    showsSponsorship,
    sourceLabel,
  } from "../../discovery/format";
  import type { Posting, PostingView } from "../../types/discovery";

  let {
    posting,
    view,
    now = new Date(),
    onaction,
  }: {
    posting: Posting;
    view: PostingView;
    now?: Date;
    onaction: (action: PostingAction) => void;
  } = $props();

  const BUTTONS: Record<PostingView, Array<{ action: PostingAction; text: string; verb: string }>> = {
    inbox: [
      { action: "save", text: "Save", verb: "Save" },
      { action: "dismiss", text: "Dismiss", verb: "Dismiss" },
    ],
    saved: [
      { action: "apply", text: "Apply", verb: "Apply to" },
      { action: "remove", text: "Remove", verb: "Remove" },
    ],
    dismissed: [{ action: "restore", text: "Restore", verb: "Restore" }],
  };

  const label = $derived(postingLabel(posting));
  const locations = $derived(shortLocations(posting.locations));
  const when = $derived(postingWhen(posting, now));
</script>

<!-- Every field comes from a list, a job board or a pasted page: plain interpolation only. -->
<article class="row">
  <div class="info">
    <div class="head">
      <strong class="company">{posting.company}</strong>
      <span class="title">{posting.title}</span>
    </div>
    <div class="meta">
      {#if locations}<span>{locations}</span>{/if}
      {#if when}<span>{when}</span>{/if}
      <span class="badge source">{sourceLabel(posting.source)}</span>
      {#if posting.closed}<span class="badge closed">closed</span>{/if}
    </div>
    {#if showsSponsorship(posting.sponsorship)}
      <span class="sponsorship">{posting.sponsorship}</span>
    {/if}
  </div>
  <div class="actions">
    {#each BUTTONS[view] as button (button.action)}
      <button type="button" aria-label="{button.verb} {label}" onclick={() => onaction(button.action)}>
        {button.text}
      </button>
    {/each}
    {#if isWebUrl(posting.url)}
      <a href={posting.url} target="_blank" rel="noopener noreferrer" aria-label="Open {label} in a new tab">Open</a>
    {/if}
  </div>
</article>

<style>
  .row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; background: #fff; }
  .info { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; flex: 1 1 18rem; }
  .head { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: baseline; }
  .company, .title { overflow-wrap: anywhere; }
  .meta { display: flex; flex-wrap: wrap; gap: 0.25rem 0.6rem; font-size: 0.8rem; color: #555; align-items: center; }
  .meta span { overflow-wrap: anywhere; }
  .badge { display: inline-block; padding: 0.05rem 0.45rem; border-radius: 999px; font-size: 0.75rem; background: #e0e0e0; color: #222; }
  .closed { background: #f6d5d3; color: #8c1d18; }
  .sponsorship { font-size: 0.8rem; color: #7a4f00; overflow-wrap: anywhere; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
  .actions button, .actions a { font-size: 0.85rem; padding: 0.2rem 0.6rem; }
</style>
