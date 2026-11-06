<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef } from "$lib/utils";

  let { ref = $bindable(null), class: className, children, ...restProps }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<div bind:this={ref} data-slot="card-footer" class={cn("flex items-center px-5", className)} {...restProps}>
  {@render children?.()}
</div>
