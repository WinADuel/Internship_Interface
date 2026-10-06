<script lang="ts">
  import { onMount } from "svelte";
  import { applications, loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";
  import KanbanBoard from "../lib/components/KanbanBoard.svelte";
  import ApplicationDetailPanel from "../lib/components/ApplicationDetailPanel.svelte";

  let selectedId = $state<number | null>(null);
  const selected = $derived($applications.find((a) => a.id === selectedId) ?? null);

  onMount(() => {
    loadApplications().catch(() => showToast("Couldn't load applications."));
  });

  function close() {
    selectedId = null;
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && selectedId !== null) close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<h1>Applications</h1>
<KanbanBoard onopen={(app) => (selectedId = app.id)} />

{#if selected}
  <aside class="detail" aria-label="Application details">
    <button type="button" class="close" onclick={close}>Close</button>
    <ApplicationDetailPanel application={selected} />
  </aside>
{/if}

<style>
  .detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(28rem, 100%); overflow-y: auto; padding: 1rem; background: #fff; border-left: 1px solid #ddd; box-shadow: -4px 0 12px rgba(0, 0, 0, 0.1); }
  .close { float: right; }
</style>
