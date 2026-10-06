<script lang="ts">
  import { getDocContent, googleDocUrl } from "../api/docs";

  let { docRef }: { docRef: string | null } = $props();

  let state = $state<"loading" | "ready" | "error">("loading");
  let content = $state("");

  $effect(() => {
    const ref = docRef;
    if (ref === null) return;
    let cancelled = false;
    state = "loading";
    getDocContent(ref).then(
      (text) => {
        if (cancelled) return;
        content = text;
        state = "ready";
      },
      () => {
        if (cancelled) return;
        state = "error";
      },
    );
    return () => {
      cancelled = true;
    };
  });
</script>

{#if docRef !== null}
  <section class="doc">
    {#if state === "loading"}
      <p>Loading doc…</p>
    {:else if state === "error"}
      <p>Couldn't load doc.</p>
      <a href={googleDocUrl(docRef)} target="_blank" rel="noopener noreferrer">Open in Google Docs</a>
    {:else}
      <pre class="content">{content}</pre>
    {/if}
  </section>
{/if}

<style>
  .content { white-space: pre-wrap; word-break: break-word; font-family: inherit; margin: 0; }
</style>
