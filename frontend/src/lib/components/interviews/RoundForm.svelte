<script lang="ts">
  import { createRound, updateRound } from "../../api/interviews";
  import { isoToLocalInput, localInputToIso } from "../../format";
  import { FORMAT_LABELS, INTERVIEW_FORMATS, INTERVIEW_KINDS, KIND_LABELS } from "../../interviews/format";
  import { showToast } from "../../stores/toast";
  import type { Application } from "../../types/application";
  import type {
    InterviewFormat,
    InterviewKind,
    InterviewRound,
    InterviewRoundDetail,
    InterviewRoundFields,
  } from "../../types/interview";

  /**
   * Adds a round (pass `applicationId`, or `applications` to choose one) or
   * edits the scheduling fields of `round`.
   */
  let {
    round = null,
    applicationId = null,
    applications = [],
    defaultKind = "other",
    submitLabel,
    save,
    create,
    onsaved,
    oncancel,
  }: {
    round?: InterviewRound | null;
    applicationId?: number | null;
    applications?: Application[];
    /** The kind a new round starts with. */
    defaultKind?: InterviewKind;
    submitLabel?: string;
    /** Sends an edit instead of a plain PATCH, for a parent that orders its round writes. */
    save?: (fields: Partial<InterviewRoundFields>) => Promise<InterviewRoundDetail>;
    /**
     * Sends a new round's fields somewhere other than POST /api/interviews (an
     * email suggestion's Accept). The parent handles the outcome; `onsaved`
     * isn't called. A thrown error is shown as a toast and the form stays.
     */
    create?: (fields: Partial<InterviewRoundFields>) => Promise<void>;
    onsaved?: (round: InterviewRoundDetail) => void;
    oncancel?: () => void;
  } = $props();

  // Seeded once; the parent re-mounts the form for another round.
  /* svelte-ignore state_referenced_locally */
  const initial = round;
  /* svelte-ignore state_referenced_locally */
  const fixedApplicationId = initial?.applicationId ?? applicationId;

  let chosenApplication = $state<number | null>(null);
  /* svelte-ignore state_referenced_locally */
  let kind = $state<InterviewKind>(initial?.kind ?? defaultKind);
  let title = $state(initial?.title ?? "");
  let when = $state(isoToLocalInput(initial?.scheduledAt ?? null));
  // A number input binds to a number, or null when blank.
  let duration = $state<number | null>(initial?.durationMinutes ?? null);
  let format = $state<InterviewFormat | "">(initial?.format ?? "");
  let location = $state(initial?.location ?? "");
  let interviewers = $state(initial?.interviewers ?? "");
  let error = $state("");
  let saving = $state(false);

  const orNull = (value: string): string | null => value.trim() || null;

  async function submit(event: Event) {
    event.preventDefault();
    if (saving) return;
    error = "";
    const appId = fixedApplicationId ?? chosenApplication;
    if (appId === null) {
      error = "Choose the application.";
      return;
    }
    const scheduledAt = localInputToIso(when);
    if (when && scheduledAt === null) {
      error = "The date and time is not valid.";
      return;
    }
    const durationMinutes = typeof duration === "number" && !Number.isNaN(duration) ? duration : null;
    if (durationMinutes !== null) {
      if (!Number.isInteger(durationMinutes) || durationMinutes < 5 || durationMinutes > 600) {
        error = "Duration must be a whole number of minutes from 5 to 600.";
        return;
      }
    }
    const fields: Partial<InterviewRoundFields> = {
      kind,
      title: orNull(title),
      scheduledAt,
      durationMinutes,
      format: format || null,
      location: orNull(location),
      interviewers: orNull(interviewers),
    };
    saving = true;
    try {
      if (!initial && create) {
        await create(fields);
        return;
      }
      const saved = initial
        ? await (save ? save(fields) : updateRound(initial.id, fields))
        : await createRound({ applicationId: appId, ...fields });
      onsaved?.(saved);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't save the round.");
    } finally {
      saving = false;
    }
  }
</script>

<form class="round-form" aria-label={initial ? "Edit round" : "New round"} novalidate onsubmit={submit}>
  {#if fixedApplicationId === null}
    <label>
      Application
      <select bind:value={chosenApplication}>
        <option value={null}>Choose…</option>
        {#each applications as app (app.id)}<option value={app.id}>{app.company} — {app.roleTitle}</option>{/each}
      </select>
    </label>
  {/if}
  <div class="row">
    <label>
      Kind
      <select bind:value={kind}>
        {#each INTERVIEW_KINDS as k (k)}<option value={k}>{k === "other" ? "Other" : KIND_LABELS[k]}</option>{/each}
      </select>
    </label>
    <label>Title <input bind:value={title} maxlength="200" placeholder="e.g. Coding round 2" autocomplete="off" /></label>
  </div>
  <div class="row">
    <label>Date and time <input type="datetime-local" bind:value={when} /></label>
    <label>Duration (minutes) <input type="number" min="5" max="600" step="5" inputmode="numeric" bind:value={duration} /></label>
  </div>
  <label>
    Format
    <select bind:value={format}>
      <option value="">Not set</option>
      {#each INTERVIEW_FORMATS as f (f)}<option value={f}>{FORMAT_LABELS[f]}</option>{/each}
    </select>
  </label>
  <label>Location or meeting link <input bind:value={location} maxlength="500" autocomplete="off" /></label>
  <label>Interviewers <input bind:value={interviewers} maxlength="500" placeholder="Names, if you know them" autocomplete="off" /></label>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <div class="actions">
    <button type="submit" disabled={saving}>{submitLabel ?? (initial ? "Save round" : "Add round")}</button>
    <button type="button" onclick={() => oncancel?.()}>Cancel</button>
  </div>
</form>

<style>
  .round-form { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; }
  label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; font-weight: 600; min-width: 0; }
  input, select { font: inherit; font-weight: 400; padding: 0.35rem; min-width: 0; max-width: 100%; box-sizing: border-box; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
  .actions { display: flex; gap: 0.5rem; }
  .error { color: #b3261e; margin: 0; }
  @media (max-width: 480px) {
    .row { grid-template-columns: 1fr; }
  }
</style>
