<script lang="ts">
  import type { Application, StatusHistoryEntry } from "../types/application";
  import { getStatusHistory } from "../api/applications";
  import GoogleDocViewer from "./GoogleDocViewer.svelte";
  import StatusBadge from "./StatusBadge.svelte";

  let { application }: { application: Application } = $props();

  let history = $state<StatusHistoryEntry[]>([]);
  let historyError = $state(false);

  $effect(() => {
    const id = application.id;
    let cancelled = false;
    historyError = false;
    getStatusHistory(id).then(
      (rows) => {
        if (!cancelled) history = rows;
      },
      () => {
        if (!cancelled) historyError = true;
      },
    );
    return () => {
      cancelled = true;
    };
  });

  const fields = $derived<Array<[string, string | null]>>([
    ["Date applied", application.dateApplied],
    ["Job link", application.jobLink],
    ["Notes", application.notes],
    ["Resume version", application.resumeVersion],
    ["Contact person", application.contactPerson],
    ["Salary range", application.salaryRange],
    ["Location", application.location],
    ["Source", application.source],
    ["Follow-up date", application.followUpDate],
    ["Interview", application.interviewDatetime],
    ["Google Doc", application.googleDocLink],
  ]);

  function label(status: string): string {
    return status.replace("_", " ");
  }
</script>

<article class="panel">
  <h2>{application.company}</h2>
  <p>{application.roleTitle}</p>
  <dl>
    <dt>Status</dt>
    <dd><StatusBadge status={application.status} /></dd>
    <dt>Priority</dt>
    <dd>{application.priority}</dd>
    {#each fields as [name, value] (name)}
      <dt>{name}</dt>
      <dd>{value ?? "—"}</dd>
    {/each}
    <dt>Archived</dt>
    <dd>{application.archived ? "Yes" : "No"}</dd>
    <dt>Created</dt>
    <dd>{application.createdAt}</dd>
    <dt>Updated</dt>
    <dd>{application.updatedAt}</dd>
  </dl>

  <h3>Status history</h3>
  {#if historyError}
    <p>Couldn't load history.</p>
  {:else}
    <ol class="history">
      {#each history as entry (entry.changedAt + entry.newStatus)}
        <li>
          {#if entry.oldStatus === null}
            Created as {label(entry.newStatus)}
          {:else}
            {label(entry.oldStatus)} → {label(entry.newStatus)}
          {/if}
          <time>{entry.changedAt}</time>
        </li>
      {/each}
    </ol>
  {/if}

  <h3>Document</h3>
  <GoogleDocViewer docRef={application.googleDocLink} />
</article>

<style>
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; }
  dt { font-weight: 600; }
  dd { margin: 0; white-space: pre-wrap; word-break: break-word; }
  time { margin-left: 0.5rem; color: #666; font-size: 0.8rem; }
</style>
