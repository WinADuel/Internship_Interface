<script lang="ts">
  import { NUDGE_LABELS } from "../../contacts/actions";
  import type { NudgeKind } from "../../types/contact";

  let { nudge }: { nudge: NudgeKind | null } = $props();
</script>

{#if nudge}
  <span class="nudge">{NUDGE_LABELS[nudge]}</span>
{/if}

<style>
  .nudge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; background: #ffe0b2; color: #6d3d00; }
</style>
