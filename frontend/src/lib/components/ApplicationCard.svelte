<script lang="ts">
  import type { Application } from "../types/application";
  import StatusBadge from "./StatusBadge.svelte";

  let { application }: { application: Application } = $props();

  function onDragStart(event: DragEvent) {
    event.dataTransfer?.setData("text/plain", String(application.id));
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  }
</script>

<article class="card" draggable="true" ondragstart={onDragStart}>
  <strong>{application.company}</strong>
  <span>{application.roleTitle}</span>
  <span class="priority">Priority: {application.priority}</span>
  <StatusBadge status={application.status} />
</article>

<style>
  .card { display: flex; flex-direction: column; gap: 0.2rem; padding: 0.6rem; background: #fff; border: 1px solid #ddd; border-radius: 6px; cursor: grab; }
  .priority { font-size: 0.8rem; color: #555; }
</style>
