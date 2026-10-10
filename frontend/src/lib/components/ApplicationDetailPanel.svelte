<script lang="ts">
  import type { Application, ApplicationStatus, StatusHistoryEntry } from "../types/application";
  import { getStatusHistory } from "../api/applications";
  import { statusLabel } from "../dashboard/widgets";
  import { formatDate, formatDateTime } from "../format";
  import { KANBAN_COLUMNS } from "../kanban/grouping";
  import { archiveAndRemoveApplication, moveApplicationStatus } from "../stores/applications";
  import { showToast } from "../stores/toast";
  import ApplicationForm from "./ApplicationForm.svelte";
  import ApplicationContacts from "./contacts/ApplicationContacts.svelte";
  import ApplicationInterviews from "./interviews/ApplicationInterviews.svelte";
  import ApplicationEmail from "./email/ApplicationEmail.svelte";
  import GoogleDocViewer from "./GoogleDocViewer.svelte";

  let { application }: { application: Application } = $props();

  let editing = $state(false);
  let archiving = $state(false);
  // Bumped after an email update is accepted here: an interview email adds a round.
  let emailChanges = $state(0);

  async function onStatusChange(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    try {
      await moveApplicationStatus(application.id, select.value as ApplicationStatus);
    } catch (err) {
      select.value = application.status; // the store already reverted; keep the control in sync
      showToast(err instanceof Error ? err.message : "Couldn't change the status.");
    }
  }

  async function archive() {
    if (archiving || !window.confirm(`Archive ${application.company} — ${application.roleTitle}?`)) return;
    archiving = true;
    try {
      await archiveAndRemoveApplication(application.id);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't archive the application.");
    } finally {
      archiving = false;
    }
  }

  let history = $state<StatusHistoryEntry[]>([]);
  let historyError = $state(false);

  $effect(() => {
    const id = application.id;
    void application.updatedAt; // reload the history after a status change or edit
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
    ["Date applied", application.dateApplied ? formatDate(application.dateApplied) : null],
    ["Job link", application.jobLink],
    ["Notes", application.notes],
    ["Resume version", application.resumeVersion],
    ["Contact person", application.contactPerson],
    ["Salary range", application.salaryRange],
    ["Location", application.location],
    ["Source", application.source],
    ["Follow-up date", application.followUpDate ? formatDate(application.followUpDate) : null],
    ["Next interview", application.interviewDatetime ? formatDateTime(application.interviewDatetime) : null],
    ["Google Doc", application.googleDocLink],
  ]);

  function label(status: string): string {
    return status.replace("_", " ");
  }
</script>

{#if editing}
  <ApplicationForm {application} onsaved={() => (editing = false)} oncancel={() => (editing = false)} />
{:else}
<article class="panel">
  <h2>{application.company}</h2>
  <p>{application.roleTitle}</p>
  <div class="actions">
    <button type="button" onclick={() => (editing = true)}>Edit</button>
    <button type="button" class="danger" disabled={archiving} onclick={archive}>Archive</button>
  </div>
  <dl>
    <dt>Status</dt>
    <dd>
      <select aria-label="Status" value={application.status} onchange={onStatusChange}>
        {#each KANBAN_COLUMNS as s (s)}<option value={s}>{statusLabel(s)}</option>{/each}
      </select>
    </dd>
    <dt>Priority</dt>
    <dd>{application.priority}</dd>
    {#each fields as [name, value] (name)}
      <dt>{name}</dt>
      <dd>{value ?? "—"}</dd>
    {/each}
    <dt>Archived</dt>
    <dd>{application.archived ? "Yes" : "No"}</dd>
    <dt>Created</dt>
    <dd>{formatDateTime(application.createdAt)}</dd>
    <dt>Updated</dt>
    <dd>{formatDateTime(application.updatedAt)}</dd>
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
          <time>{formatDateTime(entry.changedAt)}</time>
        </li>
      {/each}
    </ol>
  {/if}

  {#key emailChanges}
    <ApplicationInterviews {application} />
  {/key}

  <ApplicationEmail applicationId={application.id} onchanged={() => (emailChanges += 1)} />

  <ApplicationContacts applicationId={application.id} />

  <h3>Document</h3>
  <GoogleDocViewer docRef={application.googleDocLink} />
</article>
{/if}

<style>
  .actions { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
  .danger { color: #b3261e; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; }
  dt { font-weight: 600; }
  dd { margin: 0; white-space: pre-wrap; word-break: break-word; }
  time { margin-left: 0.5rem; color: #666; font-size: 0.8rem; }
</style>
