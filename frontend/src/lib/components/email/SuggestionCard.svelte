<script lang="ts">
  import { ApiError } from "../../api/client";
  import { acceptSuggestion, dismissSuggestion } from "../../api/email";
  import { ACTION_LABELS, KIND_LABELS, STATE_LABELS, matchLabel, safeGmailUrl, senderLabel } from "../../email/format";
  import { formatDateTime } from "../../format";
  import { afterAccept, refreshEmailStatus } from "../../stores/email";
  import { showToast } from "../../stores/toast";
  import type { AcceptInput, EmailSuggestion } from "../../types/email";
  import type { InterviewRoundFields } from "../../types/interview";
  import RoundForm from "../interviews/RoundForm.svelte";

  let {
    suggestion,
    compact = false,
    onchanged,
  }: {
    suggestion: EmailSuggestion;
    /** Inside the application panel: the application is already known, so leave it out. */
    compact?: boolean;
    /**
     * After Accept or Dismiss (the decided suggestion: show it decided or
     * drop it at once, then reload), or after a 404/409 (null: reload).
     */
    onchanged?: (updated: EmailSuggestion | null) => void;
  } = $props();

  const NAME_MAX = 200; // backend `schemas/email.py` Name

  let busy = $state(false);
  // Interview: the add-round form; new application: the company/role form.
  let editing = $state(false);
  let company = $state("");
  let roleTitle = $state("");
  let editError = $state("");

  const pending = $derived(suggestion.state === "pending");
  const gmailUrl = $derived(safeGmailUrl(suggestion.gmailUrl));
  // Inside the application panel the application is already known.
  const match = $derived(matchLabel(suggestion, { withApplication: !compact }));
  const needsForm = $derived(suggestion.kind === "interview" || suggestion.kind === "new_application");
  const headingId = $derived(`email-subject-${suggestion.id}${compact ? "-c" : ""}`);

  /**
   * Accept; a 404/409 means the list is out of date, so it is reloaded.
   * Throws nothing. After a success the buttons stay disabled: the card is
   * decided, and the list replaces or drops it.
   */
  async function accept(data: AcceptInput = {}): Promise<boolean> {
    busy = true;
    try {
      const updated = await acceptSuggestion(suggestion.id, data);
      showToast(`Accepted: ${ACTION_LABELS[suggestion.kind]}.`, "info");
      editing = false;
      onchanged?.(updated);
      await afterAccept(updated);
      return true;
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't accept: ${err.message}` : "Couldn't accept this update.");
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        void refreshEmailStatus();
        onchanged?.(null);
      }
      busy = false;
      return false;
    }
  }

  async function onAccept() {
    if (needsForm) {
      company = suggestion.proposedCompany ?? "";
      roleTitle = suggestion.proposedRole ?? "";
      editError = "";
      editing = true;
      return;
    }
    await accept();
  }

  /** The round form's submit: Accept with the round's fields (the round goes to this application). */
  async function acceptRound(fields: Partial<InterviewRoundFields>) {
    await accept({ round: fields });
  }

  async function acceptNewApplication(event: SubmitEvent) {
    event.preventDefault();
    const c = company.trim();
    const r = roleTitle.trim();
    if (!c || !r) {
      editError = "Enter the company and the role.";
      return;
    }
    editError = "";
    await accept({ company: c, roleTitle: r });
  }

  async function onDismiss() {
    busy = true;
    try {
      const updated = await dismissSuggestion(suggestion.id);
      void refreshEmailStatus();
      onchanged?.(updated); // busy stays: the card is decided
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't dismiss: ${err.message}` : "Couldn't dismiss this update.");
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        void refreshEmailStatus();
        onchanged?.(null);
      }
      busy = false;
    }
  }
</script>

<!-- Sender, subject and snippet are email text: plain interpolation only, never {@html}. -->
<article class="card" class:compact aria-labelledby={headingId}>
  <div class="meta">
    <span class="badge kind-{suggestion.kind}">{KIND_LABELS[suggestion.kind]}</span>
    {#if suggestion.direction === "sent"}<span class="badge">Sent by you</span>{/if}
    {#if !pending}<span class="badge state">{STATE_LABELS[suggestion.state]}</span>{/if}
    <time datetime={suggestion.receivedAt}>{formatDateTime(suggestion.receivedAt)}</time>
  </div>
  <strong class="subject" id={headingId}>{suggestion.subject || "(no subject)"}</strong>
  <span class="sender">From {senderLabel(suggestion)}</span>
  {#if suggestion.snippet}<p class="snippet">{suggestion.snippet}</p>{/if}
  {#if match}<p class="match">Matched: {match}</p>{/if}
  {#if pending}
    <p class="action">Suggested: {ACTION_LABELS[suggestion.kind]}</p>
  {:else if suggestion.decidedAt}
    <p class="action">{STATE_LABELS[suggestion.state]} {formatDateTime(suggestion.decidedAt)}</p>
  {/if}

  {#if editing && suggestion.kind === "interview"}
    <RoundForm
      applicationId={suggestion.applicationId}
      defaultKind={suggestion.roundKind ?? "other"}
      submitLabel="Accept and add round"
      create={acceptRound}
      oncancel={() => (editing = false)}
    />
  {:else if editing && suggestion.kind === "new_application"}
    <form class="new-app" aria-label="New application from email" novalidate onsubmit={acceptNewApplication}>
      <label>Company <input bind:value={company} maxlength={NAME_MAX} autocomplete="off" /></label>
      <label>Role <input bind:value={roleTitle} maxlength={NAME_MAX} autocomplete="off" /></label>
      {#if editError}<p class="error" role="alert">{editError}</p>{/if}
      <div class="actions">
        <button type="submit" disabled={busy}>Add to tracker</button>
        <button type="button" onclick={() => (editing = false)}>Cancel</button>
      </div>
    </form>
  {/if}

  <div class="actions">
    {#if pending && !editing}
      <button type="button" disabled={busy} aria-describedby={headingId} onclick={onAccept}>Accept</button>
      <button type="button" disabled={busy} aria-describedby={headingId} onclick={onDismiss}>Dismiss</button>
    {/if}
    {#if gmailUrl}
      <a href={gmailUrl} target="_blank" rel="noopener noreferrer" aria-describedby={headingId}>Open in Gmail</a>
    {/if}
  </div>
</article>

<style>
  .card { display: flex; flex-direction: column; gap: 0.3rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; background: #fff; min-width: 0; }
  .compact { padding: 0.45rem; font-size: 0.9rem; }
  .meta { display: flex; flex-wrap: wrap; gap: 0.25rem 0.6rem; align-items: center; font-size: 0.8rem; color: #555; }
  .badge { display: inline-block; padding: 0.05rem 0.45rem; border-radius: 999px; font-size: 0.75rem; background: #e0e0e0; color: #222; }
  .kind-rejection { background: #f6d5d3; color: #8c1d18; }
  .kind-offer, .kind-interview { background: #d7ecd9; color: #1e5b26; }
  .kind-new_application { background: #dbe7fb; color: #173f80; }
  .state { background: #fff3c4; color: #5c4700; }
  .subject, .sender, .snippet, .match { overflow-wrap: anywhere; }
  .sender { font-size: 0.85rem; color: #444; }
  .snippet { margin: 0; color: #333; font-size: 0.9rem; }
  .match, .action { margin: 0; font-size: 0.85rem; }
  .action { color: #555; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
  .actions button, .actions a { font-size: 0.85rem; padding: 0.2rem 0.6rem; }
  .new-app { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; }
  .new-app label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; font-weight: 600; }
  .new-app input { font: inherit; font-weight: 400; padding: 0.35rem; min-width: 0; max-width: 100%; box-sizing: border-box; }
  .error { color: #b3261e; margin: 0; }
</style>
