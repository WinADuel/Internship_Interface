<script lang="ts">
  import { createApplication, updateApplication } from "../api/applications";
  import { formatDateTime, localInputToIso } from "../format";
  import { upsertApplication } from "../stores/applications";
  import { showToast } from "../stores/toast";
  import { KANBAN_COLUMNS } from "../kanban/grouping";
  import { statusLabel } from "../dashboard/widgets";
  import type { Application, ApplicationInput, ApplicationStatus, Priority } from "../types/application";

  /** Pass an application to edit it; omit for create mode. */
  let {
    application = null,
    onsaved,
    oncancel,
  }: {
    application?: Application | null;
    onsaved?: (application: Application) => void;
    oncancel?: () => void;
  } = $props();

  // The form is seeded once; the parent re-mounts it (via {#key}) to edit a different application.
  /* svelte-ignore state_referenced_locally */
  const initial = application;

  let company = $state(initial?.company ?? "");
  let roleTitle = $state(initial?.roleTitle ?? "");
  let status = $state<ApplicationStatus>(initial?.status ?? "wishlist");
  let priority = $state<Priority>(initial?.priority ?? "medium");
  let dateApplied = $state(initial?.dateApplied ?? "");
  let followUpDate = $state(initial?.followUpDate ?? "");
  // Create only: becomes the application's first interview round. When editing,
  // the next interview is derived from the rounds and shown read-only.
  let interview = $state("");
  const uid = $props.id();
  let jobLink = $state(initial?.jobLink ?? "");
  let resumeVersion = $state(initial?.resumeVersion ?? "");
  let contactPerson = $state(initial?.contactPerson ?? "");
  let salaryRange = $state(initial?.salaryRange ?? "");
  let location = $state(initial?.location ?? "");
  let source = $state(initial?.source ?? "");
  let googleDocLink = $state(initial?.googleDocLink ?? "");
  let notes = $state(initial?.notes ?? "");

  let error = $state("");
  let submitting = $state(false);

  const PRIORITIES: Priority[] = ["low", "medium", "high"];

  /** Blank optional text becomes null so editing can clear a field. */
  const orNull = (value: string): string | null => value.trim() || null;

  async function submit(event: Event) {
    event.preventDefault();
    if (submitting) return;
    error = "";
    if (!company.trim()) {
      error = "Company is required.";
      return;
    }
    if (!roleTitle.trim()) {
      error = "Role title is required.";
      return;
    }
    const interviewIso = localInputToIso(interview);
    if (interview && interviewIso === null) {
      error = "Interview date and time is not valid.";
      return;
    }
    const input: Omit<ApplicationInput, "interviewDatetime"> = {
      company: company.trim(),
      roleTitle: roleTitle.trim(),
      status,
      priority,
      dateApplied: dateApplied || null,
      followUpDate: followUpDate || null,
      jobLink: orNull(jobLink),
      resumeVersion: orNull(resumeVersion),
      contactPerson: orNull(contactPerson),
      salaryRange: orNull(salaryRange),
      location: orNull(location),
      source: orNull(source),
      googleDocLink: orNull(googleDocLink),
      notes: orNull(notes),
    };
    submitting = true;
    try {
      const saved = initial
        ? await updateApplication(initial.id, input)
        : await createApplication({ ...input, interviewDatetime: interviewIso });
      upsertApplication(saved);
      onsaved?.(saved);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't save the application.");
    } finally {
      submitting = false;
    }
  }
</script>

<form aria-label="Application" novalidate onsubmit={submit}>
  <h2>{initial ? "Edit application" : "New application"}</h2>

  <label>Company <input bind:value={company} autocomplete="off" /></label>
  <label>Role title <input bind:value={roleTitle} autocomplete="off" /></label>

  <div class="row">
    <label>
      Status
      <select bind:value={status}>
        {#each KANBAN_COLUMNS as s (s)}<option value={s}>{statusLabel(s)}</option>{/each}
      </select>
    </label>
    <label>
      Priority
      <select bind:value={priority}>
        {#each PRIORITIES as p (p)}<option value={p}>{p}</option>{/each}
      </select>
    </label>
  </div>

  <div class="row">
    <label>Date applied <input type="date" bind:value={dateApplied} /></label>
    <label>Follow-up date <input type="date" bind:value={followUpDate} /></label>
  </div>
  {#if initial}
    <div class="readonly">
      <span class="label">Next interview</span>
      <span>{initial.interviewDatetime ? formatDateTime(initial.interviewDatetime) : "None scheduled"}</span>
      <span class="hint">Set by the application's interview rounds. <a href="#/interviews">Manage rounds</a></span>
    </div>
  {:else}
    <label>
      Interview date and time
      <input type="datetime-local" bind:value={interview} aria-describedby="{uid}-first-round" />
    </label>
    <span class="hint" id="{uid}-first-round">Optional: adds the application's first interview round.</span>
  {/if}

  <label>Job link <input bind:value={jobLink} inputmode="url" autocomplete="off" /></label>
  <label>Google Doc link <input bind:value={googleDocLink} inputmode="url" autocomplete="off" /></label>
  <label>Resume version <input bind:value={resumeVersion} autocomplete="off" /></label>
  <label>Contact person <input bind:value={contactPerson} autocomplete="off" /></label>
  <label>Salary range <input bind:value={salaryRange} autocomplete="off" /></label>
  <label>Location <input bind:value={location} autocomplete="off" /></label>
  <label>Source <input bind:value={source} autocomplete="off" /></label>
  <label>Notes <textarea rows="4" bind:value={notes}></textarea></label>

  {#if error}<p class="error" role="alert">{error}</p>{/if}

  <div class="actions">
    <button type="submit" disabled={submitting}>{initial ? "Save changes" : "Create application"}</button>
    <button type="button" onclick={() => oncancel?.()}>Cancel</button>
  </div>
</form>

<style>
  form { display: flex; flex-direction: column; gap: 0.6rem; }
  h2 { margin: 0; font-size: 1.1rem; }
  label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; font-weight: 600; }
  input, select, textarea { font: inherit; font-weight: 400; padding: 0.4rem; min-width: 0; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
  .actions { display: flex; gap: 0.5rem; }
  .error { color: #b3261e; margin: 0; }
  .readonly { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.9rem; }
  .readonly .label { font-size: 0.85rem; font-weight: 600; }
  .hint { font-size: 0.8rem; font-weight: 400; color: #666; }
</style>
