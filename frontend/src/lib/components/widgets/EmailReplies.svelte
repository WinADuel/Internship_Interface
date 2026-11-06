<script lang="ts">
  import { onMount, tick } from "svelte";
  import { getEmailHighlights } from "../../api/email";
  import { highlightMatch, safeGmailUrl, senderLabel, senderName, shortDate } from "../../email/format";
  import { tabKeyTarget } from "../../tabs";
  import type { EmailHighlights, EmailSuggestion, HighlightTab } from "../../types/email";

  const LIMIT = 8;
  const TABS: Array<{ id: HighlightTab; label: string; empty: string }> = [
    { id: "replies", label: "Cold emails", empty: "No cold email replies yet." },
    { id: "interview", label: "Interviews", empty: "No interview emails yet." },
    { id: "offer", label: "Offers", empty: "No offer emails yet." },
    { id: "rejection", label: "Rejections", empty: "No rejection emails yet." },
  ];

  let tab = $state<HighlightTab>("replies");
  let tabButtons: HTMLButtonElement[] = $state([]);
  let highlights = $state<EmailHighlights | null>(null);
  let failed = $state(false);
  let loading = $state(false);
  // Bumped on every load; an answer is applied only if it is still the latest.
  let latest = 0;

  async function load() {
    const request = ++latest;
    loading = true;
    try {
      const result = await getEmailHighlights(LIMIT);
      if (request !== latest) return;
      highlights = result;
      failed = false;
    } catch {
      if (request !== latest) return;
      failed = true;
    } finally {
      if (request === latest) loading = false;
    }
  }

  onMount(() => {
    void load();
  });

  async function onTabKeydown(event: KeyboardEvent, index: number) {
    const target = tabKeyTarget(event.key, index, TABS.length);
    if (target === null) return;
    event.preventDefault();
    tab = TABS[target].id;
    await tick();
    tabButtons[target]?.focus();
  }

  const current = $derived(TABS.find((t) => t.id === tab) ?? TABS[0]);
  const list = $derived(highlights?.tabs[tab] ?? { count: 0, items: [] });

  /** Subject, then Gmail's preview: the muted end of the row. */
  function preview(s: EmailSuggestion): string {
    const subject = s.subject.trim() || "(no subject)";
    const snippet = s.snippet.trim();
    return snippet ? `${subject} — ${snippet}` : subject;
  }

  /** Everything the row shows, untruncated, for its tooltip. */
  function fullText(s: EmailSuggestion, match: string | null): string {
    return [shortDate(s.receivedAt), senderLabel(s), match, preview(s)].filter(Boolean).join(" · ");
  }
</script>

{#snippet rowText(s: EmailSuggestion, match: string | null)}
  <time datetime={s.receivedAt}>{shortDate(s.receivedAt)}</time>{" "}<span class="who">{senderName(s)}</span
  >{#if match}<span class="match">{" · "}{match}</span>{/if}<span class="preview">{" · "}{preview(s)}</span>
{/snippet}

<!-- Sender, subject and snippet are email text: plain interpolation only, never {@html}. -->
<div class="widget">
  {#if failed}
    <p class="empty">Couldn't load email replies.</p>
    <button type="button" onclick={load} disabled={loading}>Retry</button>
  {:else if !highlights}
    <p class="empty">Loading…</p>
  {:else if !highlights.gmailGranted}
    <p class="empty"><a href="#/settings">Connect Gmail in Settings</a> to see replies here.</p>
  {:else}
    <div class="tabs" role="tablist" aria-label="Email replies">
      {#each TABS as t, i (t.id)}
        <button
          type="button"
          role="tab"
          id="email-replies-tab-{t.id}"
          aria-selected={tab === t.id}
          aria-controls="email-replies-panel"
          tabindex={tab === t.id ? 0 : -1}
          bind:this={tabButtons[i]}
          onclick={() => (tab = t.id)}
          onkeydown={(event) => onTabKeydown(event, i)}
        >
          {t.label} ({highlights.tabs[t.id].count})
        </button>
      {/each}
    </div>

    <div class="panel" role="tabpanel" id="email-replies-panel" aria-labelledby="email-replies-tab-{tab}">
      {#if list.items.length === 0}
        <p class="empty">{current.empty}</p>
      {:else}
        <ul>
          {#each list.items as s (s.id)}
            {@const match = highlightMatch(s, tab)}
            {@const href = safeGmailUrl(s.gmailUrl)}
            {@const rowId = `email-reply-${tab}-${s.id}`}
            <li>
              {#if href}
                <a class="row" id={rowId} {href} target="_blank" rel="noopener noreferrer" title={fullText(s, match)}>
                  {@render rowText(s, match)}
                </a>
              {:else}
                <span class="row" id={rowId} title={fullText(s, match)}>{@render rowText(s, match)}</span>
              {/if}
              {#if s.state === "pending"}
                <a class="tag" href="#/email" aria-describedby={rowId}>To review</a>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
    <p class="all"><a href="#/email">See all in Email updates</a></p>
  {/if}
</div>

<style>
  .widget { min-width: 0; }
  .tabs { display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 3px; margin-bottom: 0.5rem; border-radius: var(--radius-md); background: var(--muted); }
  .tabs button { border: 0; box-shadow: none; background: transparent; padding: 0.2rem 0.6rem; border-radius: calc(var(--radius-md) - 2px); cursor: pointer; font: inherit; font-size: 0.78rem; font-weight: 500; color: var(--muted-foreground); white-space: nowrap; }
  .tabs button:hover { background: transparent; color: var(--foreground); }
  .tabs button[aria-selected="true"] { background: var(--background); color: var(--foreground); box-shadow: 0 1px 2px rgb(0 0 0 / 0.08); }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; min-width: 0; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  /* One line: whatever doesn't fit ends in an ellipsis; the title holds the full text. */
  .row { flex: 1 1 auto; min-width: 0; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: inherit; text-decoration: none; }
  a.row:hover .who, a.row:focus-visible .who { text-decoration: underline; }
  time { color: var(--muted-foreground); font-variant-numeric: tabular-nums; }
  .who { font-weight: 600; }
  .preview { color: var(--muted-foreground); }
  .tag { flex: none; font-size: 0.7rem; font-weight: 500; padding: 0.05rem 0.45rem; border-radius: var(--radius-sm); border: 1px solid color-mix(in oklch, var(--warning) 35%, transparent); color: var(--warning); text-decoration: none; white-space: nowrap; }
  .tag:hover, .tag:focus-visible { text-decoration: underline; }
  .all { margin: 0.5rem 0 0; font-size: 0.8rem; }
  .all a { color: var(--muted-foreground); }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0 0 0.5rem; }
  button:not([role="tab"]) { font-size: 0.8rem; padding: 0.2rem 0.6rem; }
</style>
