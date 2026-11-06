<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef } from "$lib/utils";

  let { ref = $bindable(null), class: className, children, ...restProps }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<p bind:this={ref} data-slot="card-description" class={cn("m-0 text-sm text-muted-foreground", className)} {...restProps}>
  {@render children?.()}
</p>
