<script lang="ts">
  import type { ApplicationStatus } from "../types/application";

  let { status }: { status: ApplicationStatus } = $props();
  const label = $derived(status.replace("_", " "));
</script>

<span class="badge {status}">{label}</span>

<style>
  .badge { display: inline-block; flex: none; width: fit-content; padding: 0.05rem 0.45rem; border-radius: var(--radius-sm); border: 1px solid var(--border); font-size: 0.72rem; font-weight: 500; text-transform: capitalize; white-space: nowrap; color: var(--foreground); background: var(--background); }
  .offer { color: var(--success); border-color: color-mix(in oklch, var(--success) 35%, transparent); }
  .rejected { color: var(--destructive); border-color: color-mix(in oklch, var(--destructive) 35%, transparent); }
  .interview, .phone_screen { color: var(--info); border-color: color-mix(in oklch, var(--info) 35%, transparent); }
  .applied { color: var(--warning); border-color: color-mix(in oklch, var(--warning) 35%, transparent); }
</style>
