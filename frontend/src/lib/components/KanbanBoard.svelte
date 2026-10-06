<script lang="ts">
  import { applications, moveApplicationStatus } from "../stores/applications";
  import { showToast } from "../stores/toast";
  import { KANBAN_COLUMNS, groupByStatus } from "../kanban/grouping";
  import type { Application, ApplicationStatus } from "../types/application";
  import ApplicationCard from "./ApplicationCard.svelte";

  let { onopen }: { onopen?: (app: Application) => void } = $props();

  const grouped = $derived(groupByStatus($applications));

  function label(status: ApplicationStatus): string {
    const text = status.replace("_", " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  }

  async function onDrop(event: DragEvent, status: ApplicationStatus) {
    event.preventDefault();
    const raw = event.dataTransfer?.getData("text/plain") ?? "";
    if (!/^\d+$/.test(raw.trim())) return;
    try {
      await moveApplicationStatus(Number(raw), status);
    } catch {
      showToast("Couldn't move application — try again.");
    }
  }
</script>

<div class="board">
  {#each KANBAN_COLUMNS as status (status)}
    <section class="column" aria-label={label(status)} ondragover={onDragOver} ondrop={(e) => onDrop(e, status)}>
      <h2>{label(status)} ({grouped[status].length})</h2>
      {#each grouped[status] as application (application.id)}
        <ApplicationCard {application} {onopen} />
      {/each}
    </section>
  {/each}
</div>

<style>
  .board { display: flex; gap: 0.75rem; overflow-x: auto; align-items: flex-start; }
  .column { flex: 1 0 14rem; display: flex; flex-direction: column; gap: 0.5rem; padding: 0.5rem; background: #f4f4f6; border-radius: 8px; min-height: 8rem; }
  h2 { font-size: 0.95rem; margin: 0; }
</style>
