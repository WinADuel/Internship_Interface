<script lang="ts">
  import { onMount } from "svelte";
  import DashboardGrid from "../lib/components/DashboardGrid.svelte";
  import EmailReplies from "../lib/components/widgets/EmailReplies.svelte";
  import RecentActivityFeed from "../lib/components/widgets/RecentActivityFeed.svelte";
  import RemindersList from "../lib/components/widgets/RemindersList.svelte";
  import NeedsAttention from "../lib/components/widgets/NeedsAttention.svelte";
  import NewPostings from "../lib/components/widgets/NewPostings.svelte";
  import UpcomingInterviews from "../lib/components/widgets/UpcomingInterviews.svelte";
  import { loadLayout, type WidgetLayoutEntry } from "../lib/dashboard/layout";
  import { loadApplications } from "../lib/stores/applications";
  import { showToast } from "../lib/stores/toast";

  // Order: what needs you soonest first. Counts and the kanban snapshot live on Statistics.
  const defaultLayout: WidgetLayoutEntry[] = [
    { id: "interviews", x: 0, y: 0, w: 6, h: 4, settings: {} },
    { id: "needs-attention", x: 6, y: 0, w: 6, h: 4, settings: {} },
    { id: "new-postings", x: 0, y: 4, w: 6, h: 4, settings: {} },
    { id: "email-replies", x: 6, y: 4, w: 6, h: 4, settings: {} },
    { id: "reminders", x: 0, y: 8, w: 6, h: 4, settings: {} },
    { id: "activity", x: 6, y: 8, w: 6, h: 4, settings: {} },
  ];

  const titles: Record<string, string> = {
    interviews: "Upcoming interviews",
    "needs-attention": "Needs attention",
    "new-postings": "New postings",
    "email-replies": "Email replies",
    reminders: "Reminders",
    activity: "Recent activity",
  };

  const links: Record<string, { href: string; label: string }> = {
    interviews: { href: "#/interviews", label: "Interview Prep" },
    "needs-attention": { href: "#/contacts", label: "All contacts" },
    "new-postings": { href: "#/discover", label: "Discover" },
    "email-replies": { href: "#/email", label: "Email updates" },
    activity: { href: "#/applications", label: "Applications" },
  };

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

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

<header class="page-head">
  <div>
    <h1>Dashboard</h1>
    <p class="sub">{today} · what needs you today</p>
  </div>
  <a class="stats-link" href="#/statistics">View statistics</a>
</header>
<DashboardGrid bind:this={grid} {defaultLayout} {widget} />

{#snippet widget(id: string)}
  <section class="card" data-widget={id}>
    <div class="card-head">
      <h2>{titles[id]}</h2>
      {#if links[id]}<a class="more" href={links[id].href}>{links[id].label}</a>{/if}
    </div>
    <div class="card-body">
      {#if id === "interviews"}
        <UpcomingInterviews />
      {:else if id === "needs-attention"}
        <NeedsAttention />
      {:else if id === "new-postings"}
        <NewPostings />
      {:else if id === "email-replies"}
        <EmailReplies />
      {:else if id === "reminders"}
        <RemindersList withinDays={settings.reminders?.withinDays as number | undefined} onsettingschange={(s) => change(id, s)} />
      {:else if id === "activity"}
        <RecentActivityFeed limit={settings.activity?.limit as number | undefined} onsettingschange={(s) => change(id, s)} />
      {/if}
    </div>
  </section>
{/snippet}

<style>
  .page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
  h1 { margin: 0; }
  .sub { margin: 0.2rem 0 0; color: var(--muted-foreground); font-size: 0.875rem; }
  .stats-link {
    font-size: 0.85rem; font-weight: 500; color: var(--foreground); padding: 0.4rem 0.8rem;
    border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--background); box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  }
  .stats-link:hover { background: var(--accent); text-decoration: none; }

  .card {
    height: 100%; display: flex; flex-direction: column;
    background: var(--card); color: var(--card-foreground);
    border: 1px solid var(--border); border-radius: var(--radius-xl); box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
    overflow: hidden;
  }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.9rem 1.1rem 0.6rem; }
  h2 { font-size: 0.95rem; font-weight: 600; margin: 0; }
  .more { font-size: 0.8rem; color: var(--muted-foreground); white-space: nowrap; }
  .more:hover { color: var(--foreground); }
  .card-body { flex: 1; min-height: 0; overflow: auto; padding: 0 1.1rem 0.9rem; }
</style>
