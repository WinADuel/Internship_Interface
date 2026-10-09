<script lang="ts">
  import { GUESS_WARNING, fitsInGmailUrl, gmailComposeUrl } from "../../contacts/gmail";
  import { formatDateTime } from "../../format";
  import { INTERVIEW_OUTCOMES, OUTCOME_LABELS, STATE_LABELS, isThankYouDue } from "../../interviews/format";
  import { thankYouDraft } from "../../prep/prompts";
  import type { Contact } from "../../types/contact";
  import type { InterviewOutcome, InterviewRoundDetail, InterviewRoundUpdate } from "../../types/interview";
  import AutosaveText from "./AutosaveText.svelte";

  let {
    round,
    appContacts,
    patch,
    saveReflection,
  }: {
    round: InterviewRoundDetail;
    /** The application's contacts, to warn before writing to a guessed address. */
    appContacts: Contact[];
    patch: (data: InterviewRoundUpdate) => Promise<boolean>;
    saveReflection: (text: string | null) => Promise<void>;
  } = $props();

  let busy = $state(false);

  const due = $derived(isThankYouDue(round));

  async function run(data: InterviewRoundUpdate) {
    busy = true;
    try {
      await patch(data);
    } finally {
      busy = false;
    }
  }

  function onOutcome(event: Event) {
    const value = (event.currentTarget as HTMLSelectElement).value;
    void run({ outcome: (value || null) as InterviewOutcome | null });
  }

  function draftFor(name: string, email: string | null, contactId: number | null) {
    const draft = thankYouDraft({ company: round.company, roleTitle: round.roleTitle, contactName: name });
    const url = gmailComposeUrl(email ?? "", draft.subject, draft.body);
    if (!fitsInGmailUrl(url)) return;
    const guessed = appContacts.find((c) => c.id === contactId)?.emailConfidence === "pattern_guess";
    if (guessed && !window.confirm(GUESS_WARNING)) return;
    window.open(url, "_blank", "noopener");
  }
</script>

<section aria-labelledby="after-heading">
  <h2 id="after-heading">After the interview</h2>
  <div class="row">
    <span>State: <strong>{STATE_LABELS[round.state]}</strong></span>
    {#if round.state === "scheduled"}
      <button type="button" disabled={busy} onclick={() => run({ state: "done" })}>Mark done</button>
      <button type="button" disabled={busy} onclick={() => run({ state: "cancelled" })}>Mark cancelled</button>
    {:else}
      <button type="button" disabled={busy} onclick={() => run({ state: "scheduled" })}>Move back to scheduled</button>
    {/if}
  </div>

  {#if round.state === "done"}
    <label class="outcome">
      Outcome
      <select value={round.outcome ?? ""} onchange={onOutcome} disabled={busy}>
        <option value="">Not set</option>
        {#each INTERVIEW_OUTCOMES as o (o)}<option value={o}>{OUTCOME_LABELS[o]}</option>{/each}
      </select>
    </label>
  {/if}

  <AutosaveText label="How it went" value={round.reflection} save={saveReflection} maxlength={20000} rows={5}
    placeholder="What went well, what to improve, what they asked." />

  {#if round.state === "done"}
    <h3>Thank-you notes</h3>
    {#if round.thankYouSentAt}
      <p class="sent">Thank-you sent {formatDateTime(round.thankYouSentAt)}.
        <button type="button" disabled={busy} onclick={() => run({ thankYouSentAt: null })}>Undo</button>
      </p>
    {:else}
      {#if due}<p class="due" role="status">Thank-you due — send it within 24 hours of the interview.</p>{/if}
      <ul class="drafts">
        {#each round.contacts as c (c.id)}
          <li>
            <span>{c.name}{#if !c.email}<span class="muted"> (no email address — add it in Gmail)</span>{/if}</span>
            <button type="button" onclick={() => draftFor(c.name, c.email, c.id)}>Draft thank-you</button>
          </li>
        {:else}
          <li>
            <span class="muted">No interviewers linked.</span>
            <button type="button" onclick={() => draftFor("", null, null)}>Draft thank-you</button>
          </li>
        {/each}
      </ul>
      <p class="hint">Drafts open in Gmail; you send them yourself.</p>
      <button type="button" disabled={busy} onclick={() => run({ thankYouSentAt: new Date().toISOString() })}>Mark sent</button>
    {/if}
  {/if}
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  h3 { font-size: 0.95rem; margin: 0.75rem 0 0.3rem; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
  .outcome { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.5rem; font-size: 0.9rem; }
  select { font: inherit; }
  .drafts { list-style: none; margin: 0 0 0.3rem; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
  .drafts li { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem; overflow-wrap: anywhere; }
  .muted { color: #666; font-size: 0.85rem; }
  .hint { font-size: 0.8rem; color: #666; margin: 0 0 0.4rem; }
  .due { padding: 0.4rem; background: #fff3c4; border-radius: 6px; font-size: 0.9rem; }
  .sent { color: #2b7a0b; }
</style>
