<script lang="ts">
  import { toasts, dismissToast } from "../stores/toast";
</script>

<div class="toasts" aria-live="polite">
  {#each $toasts as toast (toast.id)}
    <button class="toast {toast.kind}" type="button" onclick={() => dismissToast(toast.id)}>
      {toast.text}
    </button>
  {/each}
</div>

<style>
  .toasts { position: fixed; bottom: 1rem; right: 1rem; display: flex; flex-direction: column; gap: 0.5rem; z-index: 1000; }
  .toast { border: 0; border-radius: 6px; padding: 0.6rem 1rem; color: #fff; cursor: pointer; text-align: left; }
  .error { background: #b3261e; }
  .info { background: #1f5fbf; }
</style>
