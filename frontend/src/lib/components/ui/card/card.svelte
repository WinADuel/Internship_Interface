<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef } from "$lib/utils";

  let { ref = $bindable(null), class: className, children, ...restProps }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<section
  bind:this={ref}
  data-slot="card"
  class={cn("flex flex-col gap-4 rounded-xl border border-border bg-card py-5 text-card-foreground shadow-xs", className)}
  {...restProps}
>
  {@render children?.()}
</section>
