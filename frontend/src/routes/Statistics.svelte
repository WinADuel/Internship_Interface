<script lang="ts">
  import { onMount } from "svelte";
  import * as Card from "$lib/components/ui/card";
  import { listRounds } from "../lib/api/interviews";
  import BucketPreview from "../lib/components/widgets/BucketPreview.svelte";
  import KanbanSnapshot from "../lib/components/widgets/KanbanSnapshot.svelte";
  import { applicationStats, scheduledInterviews } from "../lib/dashboard/statistics";
  import { formatRoundTime } from "../lib/interviews/format";
  import { applications, loadApplications } from "../lib/stores/applications";
  import { clock } from "../lib/stores/clock";
  import { emailStatus, refreshEmailStatus } from "../lib/stores/email";
  import { showToast } from "../lib/stores/toast";
  import type { InterviewRoundListItem } from "../lib/types/interview";

  const SETTINGS_KEY = "statistics-settings-v1";
  type Settings = { snapshot: { hideEmpty?: boolean }; buckets: { limit?: number } };

  function readSettings(): Settings {
    try {
      const parsed = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
      return { snapshot: parsed.snapshot ?? {}, buckets: parsed.buckets ?? {} };
    } catch {
      return { snapshot: {}, buckets: {} };
    }
  }

  let settings = $state<Settings>(readSettings());
  function change<K extends keyof Settings>(key: K, value: Settings[K]) {
    settings[key] = { ...settings[key], ...value };
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify($state.snapshot(settings)));
    } catch {
      // storage unavailable: the choice lasts until the page is closed
    }
  }

  let rounds = $state<InterviewRoundListItem[]>([]);
  let roundsFailed = $state(false);

  onMount(() => {
    loadApplications().catch(() => showToast("Couldn't load applications."));
    void refreshEmailStatus();
    listRounds({ scope: "all" })
      .then((r) => (rounds = r))
      .catch(() => (roundsFailed = true));
  });

  const stats = $derived(applicationStats($applications, $clock));
  const upcoming = $derived(scheduledInterviews(rounds, $clock));
  const pending = $derived($emailStatus?.pendingCount ?? 0);
  const inboxes = $derived($emailStatus?.accounts.length ?? 0);
</script>

<header class="page-head">
  <h1>Statistics</h1>
  <p class="sub">How your search is going overall.</p>
</header>

<section class="tiles" aria-label="Summary">
  <Card.Root class="tile" data-stat="sent">
    <Card.Content class="tile-body">
      <span class="label">Applications sent</span>
      <span class="value">{stats.sent}</span>
      <span class="hint">{#if stats.sentLast7Days > 0}<b>+{stats.sentLast7Days}</b> in the last 7 days{:else}None in the last 7 days{/if}</span>
    </Card.Content>
  </Card.Root>
  <Card.Root class="tile" data-stat="interviews">
    <Card.Content class="tile-body">
      <span class="label">Interviews scheduled</span>
      <span class="value">{roundsFailed ? "–" : upcoming.length}</span>
      <span class="hint">
        {#if roundsFailed}Couldn't load interviews{:else if upcoming[0]}Next: {upcoming[0].company}, {formatRoundTime(upcoming[0].scheduledAt as string)}{:else}Nothing on the calendar{/if}
      </span>
    </Card.Content>
  </Card.Root>
  <Card.Root class="tile" data-stat="replies">
    <Card.Content class="tile-body">
      <span class="label">Replies to review</span>
      <span class="value">{pending}</span>
      <span class="hint">
        {#if inboxes > 0}From {inboxes} {inboxes === 1 ? "inbox" : "inboxes"} · <a href="#/email">Review</a>{:else}<a href="#/settings">Connect Gmail</a> to see replies{/if}
      </span>
    </Card.Content>
  </Card.Root>
  <Card.Root class="tile" data-stat="response-rate">
    <Card.Content class="tile-body">
      <span class="label">Response rate</span>
      <span class="value">{stats.responseRate === null ? "–" : `${stats.responseRate}%`}</span>
      <span class="hint">Heard back on {stats.heardBack} of {stats.sent} sent</span>
    </Card.Content>
  </Card.Root>
</section>

<div class="panels">
  <Card.Root class="panel" data-widget="snapshot">
    <Card.Header>
      <Card.Title>Kanban snapshot</Card.Title>
      <a class="more" href="#/applications">Open board</a>
    </Card.Header>
    <Card.Content>
      <KanbanSnapshot hideEmpty={settings.snapshot.hideEmpty} onsettingschange={(s) => change("snapshot", s)} />
    </Card.Content>
  </Card.Root>
  <Card.Root class="panel" data-widget="buckets">
    <Card.Header>
      <Card.Title>Buckets</Card.Title>
    </Card.Header>
    <Card.Content>
      <BucketPreview limit={settings.buckets.limit} onsettingschange={(s) => change("buckets", s)} />
    </Card.Content>
  </Card.Root>
</div>

<style>
  .page-head { margin-bottom: 1rem; }
  h1 { margin: 0; }
  .sub { margin: 0.2rem 0 0; color: var(--muted-foreground); font-size: 0.875rem; }
  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.9rem; margin-bottom: 0.9rem; }
  .tiles :global(.tile) { padding-block: 1rem; }
  .tiles :global(.tile-body) { display: flex; flex-direction: column; gap: 0.3rem; }
  .label { font-size: 0.8rem; font-weight: 500; color: var(--muted-foreground); }
  .value { font-size: 1.85rem; font-weight: 600; letter-spacing: -0.02em; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .hint { font-size: 0.78rem; color: var(--muted-foreground); overflow-wrap: anywhere; }
  .hint b { color: var(--success); font-weight: 600; }
  .panels { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 0.9rem; align-items: start; }
  .more { font-size: 0.8rem; color: var(--muted-foreground); }
  .more:hover { color: var(--foreground); }

  @media (max-width: 1000px) {
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .panels { grid-template-columns: minmax(0, 1fr); }
  }
</style>
