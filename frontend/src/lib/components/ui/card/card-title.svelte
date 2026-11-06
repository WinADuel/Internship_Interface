<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef } from "$lib/utils";

  let { ref = $bindable(null), class: className, children, ...restProps }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<h2 bind:this={ref} data-slot="card-title" class={cn("m-0 text-[0.95rem] leading-none font-semibold", className)} {...restProps}>
  {@render children?.()}
</h2>
