<script lang="ts">
  import { getDocContent, googleDocUrl } from "../api/docs";

  let { docRef }: { docRef: string | null } = $props();

  let status = $state<"loading" | "ready" | "error">("loading");
  let content = $state("");

  $effect(() => {
    const ref = docRef;
    if (ref === null) return;
    let cancelled = false;
    status = "loading";
    getDocContent(ref).then(
      (text) => {
        if (cancelled) return;
        content = text;
        status = "ready";
      },
      () => {
        if (cancelled) return;
        status = "error";
      },
    );
    return () => {
      cancelled = true;
    };
  });
</script>

{#if docRef !== null}
  <section class="doc">
    {#if status === "loading"}
      <p>Loading doc…</p>
    {:else if status === "error"}
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
