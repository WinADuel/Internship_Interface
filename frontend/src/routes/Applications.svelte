<script lang="ts">
  import { onMount } from "svelte";
  import { applications, loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";
  import KanbanBoard from "../lib/components/KanbanBoard.svelte";
  import ApplicationDetailPanel from "../lib/components/ApplicationDetailPanel.svelte";
  import ApplicationForm from "../lib/components/ApplicationForm.svelte";

  let selectedId = $state<number | null>(null);
  let creating = $state(false);
  const selected = $derived($applications.find((a) => a.id === selectedId) ?? null);

  onMount(() => {
    loadApplications().catch(() => showToast("Couldn't load applications."));
  });

  function close() {
    selectedId = null;
    creating = false;
  }

  function startCreate() {
    selectedId = null;
    creating = true;
  }

  function open(id: number) {
    creating = false;
    selectedId = id;
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && (selectedId !== null || creating)) close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="header">
  <h1>Applications</h1>
  <button type="button" onclick={startCreate}>New application</button>
</div>
<KanbanBoard onopen={(app) => open(app.id)} />

{#if creating}
  <aside class="detail" aria-label="New application">
    <button type="button" class="close" onclick={close}>Close</button>
    <ApplicationForm
      onsaved={(app) => {
        creating = false;
        selectedId = app.id;
      }}
      oncancel={close}
    />
  </aside>
{:else if selected}
  <aside class="detail" aria-label="Application details">
    <button type="button" class="close" onclick={close}>Close</button>
    {#key selected.id}
      <ApplicationDetailPanel application={selected} />
    {/key}
  </aside>
{/if}

<style>
  .header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(28rem, 100%); box-sizing: border-box; overflow-y: auto; padding: 1rem; background: #fff; border-left: 1px solid #ddd; box-shadow: -4px 0 12px rgba(0, 0, 0, 0.1); z-index: 10; }
  .close { float: right; }

  /* Phones: the panel takes the whole screen so nothing sits half-hidden behind it. */
  @media (max-width: 700px) {
    .detail { width: 100%; border-left: 0; }
  }
</style>
