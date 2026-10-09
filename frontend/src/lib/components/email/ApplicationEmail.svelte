<script lang="ts">
  import { listSuggestions } from "../../api/email";
  import type { EmailSuggestion } from "../../types/email";
  import SuggestionCard from "./SuggestionCard.svelte";

  let {
    applicationId,
    onchanged,
  }: {
    applicationId: number;
    /** After an Accept or Dismiss here, so the panel can reload what the email changed. */
    onchanged?: () => void;
  } = $props();

  const LIMIT = 50;

  let items = $state<EmailSuggestion[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let reloads = $state(0);

  $effect(() => {
    const id = applicationId;
    void reloads;
    let cancelled = false;
    listSuggestions({ state: "all", applicationId: id, limit: LIMIT }).then(
      (rows) => {
        if (cancelled) return;
        items = rows;
        failed = false;
        loaded = true;
      },
      () => {
        if (cancelled) return;
        failed = true;
        loaded = true;
      },
    );
    return () => {
      cancelled = true;
    };
  });

  function changed() {
    reloads += 1;
    onchanged?.();
  }
</script>

<section class="app-email" aria-label="Email">
  <h3>Email</h3>
  {#if failed}
    <p class="empty">Couldn't load this application's emails.</p>
  {:else if loaded && items.length === 0}
    <p class="empty">No emails matched to this application yet.</p>
  {:else}
    <div class="list">
      {#each items as s (s.id)}
        <SuggestionCard suggestion={s} compact onchanged={changed} />
      {/each}
    </div>
  {/if}
</section>

<style>
  h3 { margin: 0.75rem 0 0.3rem; }
  .list { display: flex; flex-direction: column; gap: 0.4rem; }
  .empty { color: #666; font-size: 0.85rem; }
</style>
