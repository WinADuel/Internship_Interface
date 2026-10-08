<script lang="ts">
  import { onMount } from "svelte";
  import { replace, router } from "svelte-spa-router";
  import GoogleDocViewer from "../lib/components/GoogleDocViewer.svelte";
  import { updateApplication } from "../lib/api/applications";
  import { promptTemplates } from "../lib/data/promptTemplates";
  import { applications, loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";

  let selectedId = $state<number | null>(null);
  let linkInput = $state("");
  let saving = $state(false);
  let connectedHandled = false;

  const selected = $derived(
    $applications.find((a) => a.id === selectedId) ?? $applications[0] ?? null,
  );

  // Reset the input whenever the effective selection (or its saved link) changes.
  $effect(() => {
    linkInput = selected?.googleDocLink ?? "";
  });

  $effect(() => {
    if (connectedHandled) return;
    if (new URLSearchParams(router.querystring ?? "").get("connected") === "1") {
      connectedHandled = true;
      showToast("Google Docs connected.", "info");
      void replace("/essays");
    }
  });

  onMount(() => {
    loadApplications().catch((err) =>
      showToast(err instanceof Error ? err.message : "Could not load applications."),
    );
  });

  async function copyPrompt(text: string) {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      showToast("Copied.", "info");
    } catch {
      showToast("Could not copy. Select the text and copy it manually.");
    }
  }

  async function saveLink() {
    if (!selected) return;
    const value = linkInput.trim();
    saving = true;
    try {
      const updated = await updateApplication(selected.id, {
        googleDocLink: value === "" ? null : value,
      });
      applications.update((all) => all.map((a) => (a.id === updated.id ? updated : a)));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not save link.");
    } finally {
      saving = false;
    }
  }
</script>

<h1>Essays</h1>

<section>
  <h2>Prompt library</h2>
  <p>
    Copy a prompt, then paste it into
    <a href="https://claude.ai" target="_blank" rel="noopener noreferrer">claude.ai</a>.
  </p>
  {#each promptTemplates as template (template.id)}
    <article class="template">
      <h3>{template.title}</h3>
      <pre class="prompt">{template.prompt}</pre>
      <button type="button" onclick={() => copyPrompt(template.prompt)}>Copy</button>
    </article>
  {/each}
</section>

<section>
  <h2>Linked Google Doc</h2>
  <p><a href="/api/docs/google/authorize">Connect Google Docs</a></p>
  {#if $applications.length === 0}
    <p>No applications yet.</p>
  {:else if selected}
    <label>
      Application
      <select bind:value={selectedId}>
        {#each $applications as app (app.id)}
          <option value={app.id} selected={app.id === selected.id}>
            {app.company} - {app.roleTitle}
          </option>
        {/each}
      </select>
    </label>
    <div class="link-row">
      <label>
        Google Doc link
        <input type="text" bind:value={linkInput} placeholder="Doc id or docs.google.com URL" />
      </label>
      <button type="button" onclick={saveLink} disabled={saving}>Save link</button>
    </div>
    <GoogleDocViewer docRef={selected.googleDocLink} />
  {/if}
</section>

<style>
  .prompt {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    user-select: text;
  }
  .template { margin-bottom: 1rem; }
  .link-row { display: flex; gap: 0.5rem; align-items: end; margin: 0.5rem 0; }
</style>
