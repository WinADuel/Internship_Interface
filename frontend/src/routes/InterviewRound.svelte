<script lang="ts">
  import RoundPrep from "../lib/components/interviews/RoundPrep.svelte";

  let { params = {} }: { params?: { id?: string } } = $props();

  const id = $derived(Number(params.id));
</script>

<p class="back"><a href="#/interviews">← Interview Prep</a></p>

<!-- The router reuses this page when only :id changes; a fresh RoundPrep per
     round keeps one round's saves and answers away from the next. -->
{#key id}
  <RoundPrep roundId={id} />
{/key}

<style>
  .back { margin: 0 0 0.5rem; }
</style>
