<script lang="ts" module>
  export type PostingAction = "save" | "dismiss" | "apply" | "remove" | "restore";
</script>

<script lang="ts">
  import {
    bestScore,
    isWebUrl,
    postingWhen,
    postingLabel,
    shortLocations,
    showsSponsorship,
    sourceLabel,
    TOP_PICKS_SCORE,
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

  // Ranking: Dismissed postings aren't re-scored, so their scores aren't shown.
  const ranked = $derived(view !== "dismissed");
  const score = $derived(ranked ? bestScore(posting) : null);
  const byClaude = $derived(posting.claudeScore !== null);
  const stale = $derived(byClaude && posting.claudeStale);
  const scoreLabel = $derived(`${byClaude ? "Claude score" : "Match score"} ${score} of 100`);
</script>

<!-- Every field comes from a list, a job board or a pasted page: plain interpolation only. -->
<article class="row">
  <div class="info">
    <div class="head">
      {#if score !== null}
        <span class="score" class:top={!stale && score >= TOP_PICKS_SCORE} class:stale title={scoreLabel}>
          <span class="visually-hidden">{scoreLabel}</span>
          <span aria-hidden="true">{score}{#if byClaude}<span class="c-mark">C</span>{/if}</span>
        </span>
      {/if}
      <strong class="company">{posting.company}</strong>
      <span class="title">{posting.title}</span>
    </div>
    <div class="meta">
      {#if locations}<span>{locations}</span>{/if}
      {#if when}<span>{when}</span>{/if}
      <span class="badge source">{sourceLabel(posting.source)}</span>
      {#if posting.closed}<span class="badge closed">closed</span>{/if}
      {#if score !== null && stale}<span class="stale-note">preferences changed since</span>{/if}
    </div>
    {#if showsSponsorship(posting.sponsorship)}
      <span class="sponsorship">{posting.sponsorship}</span>
    {/if}
    {#if score !== null}
      <!-- Reasons are built by the app from posting fields; the Claude note is untrusted: text only. -->
      <details class="why">
        <summary aria-label="Why? {label}">Why?</summary>
        {#if posting.localScore !== null}
          <p>Match score {posting.localScore}</p>
          {#if posting.localReasons.length}
            <ul>
              {#each posting.localReasons as reason, i (i)}<li>{reason}</li>{/each}
            </ul>
          {/if}
        {/if}
        {#if posting.claudeScore !== null}
          <p>
            Claude score {posting.claudeScore}
            {#if posting.claudeStale}<span class="stale-note">(preferences changed since)</span>{/if}
          </p>
          {#if posting.claudeNote}<p class="note">{posting.claudeNote}</p>{/if}
        {/if}
      </details>
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
  .score { display: inline-flex; align-items: baseline; padding: 0.05rem 0.45rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600; background: #e8eef7; color: #1a3d6d; }
  .score.top { background: #d7f0dc; color: #14532d; }
  .score.stale { background: #eee; color: #777; font-weight: 400; }
  .c-mark { margin-left: 0.15rem; font-size: 0.65rem; font-weight: 700; opacity: 0.8; }
  .stale-note { color: #777; font-style: italic; }
  .why { font-size: 0.8rem; color: #444; }
  .why summary { cursor: pointer; color: #1a5fb4; width: fit-content; }
  .why p { margin: 0.25rem 0 0; overflow-wrap: anywhere; }
  .why ul { margin: 0.15rem 0 0; padding-left: 1.1rem; }
  .why li { overflow-wrap: anywhere; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
  .actions button, .actions a { font-size: 0.85rem; padding: 0.2rem 0.6rem; }
</style>
