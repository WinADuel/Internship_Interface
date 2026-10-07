<script lang="ts">
  import { onMount } from "svelte";
  import DashboardGrid from "../lib/components/DashboardGrid.svelte";
  import RecentActivityFeed from "../lib/components/widgets/RecentActivityFeed.svelte";
  import RemindersList from "../lib/components/widgets/RemindersList.svelte";
  import BucketPreview from "../lib/components/widgets/BucketPreview.svelte";
  import KanbanSnapshot from "../lib/components/widgets/KanbanSnapshot.svelte";
  import { loadLayout, type WidgetLayoutEntry } from "../lib/dashboard/layout";
  import { loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";

  const defaultLayout: WidgetLayoutEntry[] = [
    { id: "activity", x: 0, y: 0, w: 6, h: 4, settings: {} },
    { id: "reminders", x: 6, y: 0, w: 6, h: 4, settings: {} },
    { id: "buckets", x: 0, y: 4, w: 6, h: 4, settings: {} },
    { id: "snapshot", x: 6, y: 4, w: 6, h: 4, settings: {} },
  ];

  const titles: Record<string, string> = {
    activity: "Recent activity",
    reminders: "Reminders",
    buckets: "Buckets",
    snapshot: "Kanban snapshot",
  };

  let grid: { updateSettings: (id: string, s: Record<string, unknown>) => void } | undefined;
  // Mirrors what the grid persists; read once from the reconciled saved layout.
  let settings: Record<string, Record<string, unknown>> = $state(
    Object.fromEntries(loadLayout(defaultLayout).map((e) => [e.id, e.settings])),
  );

  function change(id: string, s: Record<string, unknown>) {
    settings[id] = { ...settings[id], ...s };
    grid?.updateSettings(id, s);
  }

  onMount(() => {
    loadApplications().catch(() => showToast("Couldn't load applications."));
  });
</script>

<h1>Dashboard</h1>
<DashboardGrid bind:this={grid} {defaultLayout} {widget} />

{#snippet widget(id: string)}
  <section class="card" data-widget={id}>
    <h2>{titles[id]}</h2>
    {#if id === "activity"}
      <RecentActivityFeed limit={settings.activity?.limit as number | undefined} onsettingschange={(s) => change(id, s)} />
    {:else if id === "reminders"}
      <RemindersList withinDays={settings.reminders?.withinDays as number | undefined} onsettingschange={(s) => change(id, s)} />
    {:else if id === "buckets"}
      <BucketPreview limit={settings.buckets?.limit as number | undefined} onsettingschange={(s) => change(id, s)} />
    {:else if id === "snapshot"}
      <KanbanSnapshot hideEmpty={settings.snapshot?.hideEmpty as boolean | undefined} onsettingschange={(s) => change(id, s)} />
    {/if}
  </section>
{/snippet}

<style>
  .card { height: 100%; overflow: auto; }
  h2 { font-size: 1rem; margin: 0 0 0.5rem; }
</style>
