<script lang="ts">
  import { onMount } from "svelte";
  import type { Snippet } from "svelte";
  import { GridStack } from "gridstack";
  import "gridstack/dist/gridstack.min.css";
  import { loadLayout, saveLayout, type WidgetLayoutEntry } from "../dashboard/layout";

  let { defaultLayout, widget }: {
    defaultLayout: WidgetLayoutEntry[];
    widget: Snippet<[string]>;
  } = $props();

  // Layout is read once at mount; Gridstack owns positions afterwards.
  let layout: WidgetLayoutEntry[] = $state(loadLayout(defaultLayout));
  let container: HTMLElement;

  onMount(() => {
    const grid = GridStack.init({ cellHeight: 80, margin: 8, float: false }, container);
    grid.on("change", () => {
      const saved = grid.save(false) as { id?: string | number; x?: number; y?: number; w?: number; h?: number }[];
      const byId = new Map(saved.map((n) => [String(n.id), n]));
      layout = layout.map((entry) => {
        const n = byId.get(entry.id);
        return n
          ? { ...entry, x: n.x ?? entry.x, y: n.y ?? entry.y, w: n.w ?? entry.w, h: n.h ?? entry.h }
          : entry;
      });
      saveLayout($state.snapshot(layout));
    });
    return () => grid.destroy(false);
  });
</script>

<div class="grid-stack" bind:this={container}>
  {#each layout as entry (entry.id)}
    <div
      class="grid-stack-item"
      gs-id={entry.id}
      gs-x={entry.x}
      gs-y={entry.y}
      gs-w={entry.w}
      gs-h={entry.h}
    >
      <div class="grid-stack-item-content">
        {@render widget(entry.id)}
      </div>
    </div>
  {/each}
</div>
