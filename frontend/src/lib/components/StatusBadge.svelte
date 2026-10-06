<script lang="ts">
  import type { ApplicationStatus } from "../types/application";

  let { status }: { status: ApplicationStatus } = $props();
  const label = $derived(status.replace("_", " "));
</script>

<span class="badge {status}">{label}</span>

<style>
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; text-transform: capitalize; background: #e0e0e0; color: #222; }
  .offer { background: #c8e6c9; }
  .rejected { background: #f4c7c3; }
  .interview, .phone_screen { background: #bbdefb; }
  .applied { background: #fff3c4; }
</style>
