<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { push } from "svelte-spa-router";
  import AfterInterview from "./AfterInterview.svelte";
  import AutosaveText from "./AutosaveText.svelte";
  import CompanyBrief from "./CompanyBrief.svelte";
  import PrepChecklist from "./PrepChecklist.svelte";
  import PrepPrompts from "./PrepPrompts.svelte";
  import RoundForm from "./RoundForm.svelte";
  import RoundInterviewers from "./RoundInterviewers.svelte";
  import RoundStories from "./RoundStories.svelte";
  import { getApplication } from "../../api/applications";
  import { ApiError } from "../../api/client";
  import { listContacts } from "../../api/contacts";
  import { calendarUrl, deleteRound, getRound, setRoundContacts, setRoundStories, updateRound } from "../../api/interviews";
  import { getSettings } from "../../api/settings";
  import { isSafeHttpUrl } from "../../contacts/links";
  import { FORMAT_LABELS, STATE_LABELS, countdown, formatRoundTime, roundName } from "../../interviews/format";
  import type { PromptContext } from "../../prep/prompts";
  import { clock } from "../../stores/clock";
  import { showToast } from "../../stores/toast";
  import type { Application } from "../../types/application";
  import type { Contact } from "../../types/contact";
  import type { ChecklistItem, InterviewRoundDetail, InterviewRoundUpdate } from "../../types/interview";

  /**
   * One round's prep page. The route re-mounts it when the round id changes,
   * so `roundId` is fixed for its lifetime: notes still unsaved when it goes
   * save to their own round, and a late answer can't reach the next page.
   */
  let { roundId }: { roundId: number } = $props();

  let round = $state<InterviewRoundDetail | null>(null);
  let application = $state<Application | null>(null);
  let outreachProfile = $state("");
  let appContacts = $state<Contact[]>([]);
  let status = $state<"loading" | "ready" | "missing" | "failed">("loading");
  let editing = $state(false);
  let deleting = $state(false);
  let gone = false;

  function loadContacts(applicationId: number) {
    listContacts({ applicationId }).then(
      (rows) => !gone && (appContacts = rows),
      () => {},
    );
  }

  onMount(() => {
    if (!Number.isInteger(roundId) || roundId <= 0) {
      status = "missing";
      return;
    }
    getRound(roundId).then(
      (r) => {
        if (gone) return;
        round = r;
        status = "ready";
        // Extras for prompts and the interviewer picker; the page works without them.
        getApplication(r.applicationId).then((a) => !gone && (application = a), () => {});
        loadContacts(r.applicationId);
      },
      (err) => {
        if (gone) return;
        status = err instanceof ApiError && err.status === 404 ? "missing" : "failed";
      },
    );
    // For the "Tell me about yourself" prompt; a placeholder is used without it.
    getSettings().then((s) => !gone && (outreachProfile = s.outreachProfile ?? ""), () => {});
  });

  onDestroy(() => {
    gone = true;
  });

  // Every round write (PATCH and both PUTs) answers with the whole round, and
  // answers can come back out of order. One older than the newest answer
  // already applied is dropped, and the fields a newer write still in flight
  // sent keep their local value (the optimistic checklist), so a slow answer
  // can't undo a newer edit.
  type Field = keyof InterviewRoundDetail;
  let issued = 0;
  let applied = 0;
  const inFlight = new Map<number, Field[]>();

  /** Sends one round write and applies its answer; rejects when it fails. */
  async function write(fields: Field[], send: () => Promise<InterviewRoundDetail>): Promise<InterviewRoundDetail> {
    const ticket = ++issued;
    inFlight.set(ticket, fields);
    try {
      const saved = await send();
      if (!gone && round && saved.id === roundId && ticket > applied) {
        applied = ticket;
        const current = round;
        const newer = [...inFlight].filter(([t]) => t > ticket).flatMap(([, sent]) => sent);
        round = { ...saved, ...Object.fromEntries(newer.map((f) => [f, current[f]])) };
      }
      return saved;
    } finally {
      inFlight.delete(ticket);
    }
  }

  /** Saves fields of the round; throws on failure. */
  async function patchRaw(data: InterviewRoundUpdate): Promise<void> {
    await write(Object.keys(data) as Field[], () => updateRound(roundId, data));
  }

  /** Saves, toasting on failure. */
  async function patch(data: InterviewRoundUpdate): Promise<boolean> {
    try {
      await patchRaw(data);
      return true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't save the round.");
      return false;
    }
  }

  let checklistEdits = 0;

  async function onChecklist(next: ChecklistItem[]) {
    if (!round) return;
    const before = round.checklist;
    const edit = ++checklistEdits;
    round.checklist = next; // optimistic; the response brings ids for new items
    const ok = await patch({ checklist: next.map((i) => (i.id ? i : { label: i.label, done: i.done })) });
    // A newer edit's list stays on screen; its own answer settles it.
    if (!ok && round && edit === checklistEdits) round.checklist = before;
  }

  async function saveContacts(ids: number[]): Promise<void> {
    const saved = await write(["contacts"], () => setRoundContacts(roundId, ids));
    if (!gone) loadContacts(saved.applicationId);
  }

  async function saveStories(ids: number[]): Promise<void> {
    await write(["stories"], () => setRoundStories(roundId, ids));
  }

  async function remove() {
    if (!round || deleting) return;
    if (!window.confirm(`Delete this round (${roundName(round)}) and its prep notes?`)) return;
    deleting = true;
    try {
      await deleteRound(round.id);
      await push("/interviews");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't delete the round.");
    } finally {
      deleting = false;
    }
  }

  const now = $derived($clock);

  const promptContext = $derived<PromptContext | null>(
    round && {
      company: round.company,
      roleTitle: round.roleTitle,
      jobLink: application?.jobLink ?? null,
      roundName: roundName(round),
      kind: round.kind,
      durationMinutes: round.durationMinutes,
      interviewerNames: round.contacts.length
        ? round.contacts.map((c) => c.name)
        : (round.interviewers ?? "").split(",").map((n) => n.trim()).filter(Boolean),
      storyTitles: round.stories.map((s) => s.title),
      outreachProfile,
    },
  );
</script>

{#if status === "loading"}
  <p>Loading…</p>
{:else if status === "missing"}
  <p>This interview round doesn't exist. It may have been deleted.</p>
{:else if status === "failed"}
  <p>Couldn't load this interview round.</p>
{:else if round}
  <article class="prep">
    <header>
      <h1>{round.company} — {round.roleTitle}</h1>
      <p class="round-name">{roundName(round)} <span class="state">{STATE_LABELS[round.state]}</span></p>
      {#if editing}
        <RoundForm
          {round}
          save={(fields) => write(Object.keys(fields) as Field[], () => updateRound(roundId, fields))}
          onsaved={() => (editing = false)}
          oncancel={() => (editing = false)}
        />
        <button type="button" class="danger" disabled={deleting} onclick={remove}>Delete round</button>
      {:else}
        <dl>
          <dt>When</dt>
          <dd>
            {#if round.scheduledAt}
              {formatRoundTime(round.scheduledAt)}
              <span class="countdown">({countdown(round.scheduledAt, now)})</span>
            {:else}
              Not scheduled yet
            {/if}
          </dd>
          {#if round.durationMinutes}<dt>Length</dt><dd>{round.durationMinutes} minutes</dd>{/if}
          {#if round.format}<dt>Format</dt><dd>{FORMAT_LABELS[round.format]}</dd>{/if}
          {#if round.location}
            <dt>Where</dt>
            <dd>
              {#if isSafeHttpUrl(round.location)}
                <a href={round.location.trim()} target="_blank" rel="noopener noreferrer">{round.location}</a>
              {:else}
                {round.location}
              {/if}
            </dd>
          {/if}
          {#if round.interviewers}<dt>Interviewers</dt><dd>{round.interviewers}</dd>{/if}
        </dl>
        <div class="actions">
          {#if round.scheduledAt}
            <a class="button" href={calendarUrl(round.id)} download>Add to calendar</a>
          {/if}
          <button type="button" onclick={() => (editing = true)}>Edit</button>
        </div>
      {/if}
    </header>

    <PrepChecklist items={round.checklist} onchange={onChecklist} />

    <section class="notes" aria-label="Notes">
      <AutosaveText label="Prep notes" value={round.prepNotes} save={(text) => patchRaw({ prepNotes: text })} maxlength={20000} />
      <AutosaveText label="Questions to ask" value={round.questionsToAsk} save={(text) => patchRaw({ questionsToAsk: text })} maxlength={5000} rows={4} />
    </section>

    <RoundStories linked={round.stories} save={saveStories} />

    <RoundInterviewers
      applicationId={round.applicationId}
      company={round.company}
      linked={round.contacts}
      {appContacts}
      save={saveContacts}
    />

    <CompanyBrief applicationId={round.applicationId} />

    {#if promptContext}<PrepPrompts context={promptContext} />{/if}

    <AfterInterview {round} {appContacts} {patch} saveReflection={(text) => patchRaw({ reflection: text })} />
  </article>
{/if}

<style>
  .prep { display: flex; flex-direction: column; gap: 1.25rem; max-width: 48rem; }
  .prep > :global(section) { border-top: 1px solid #e5e5e5; padding-top: 0.75rem; }
  h1 { font-size: 1.4rem; margin: 0; overflow-wrap: anywhere; }
  .round-name { margin: 0.2rem 0 0.5rem; font-size: 1.05rem; overflow-wrap: anywhere; }
  .state { font-size: 0.75rem; padding: 0.05rem 0.45rem; border-radius: 999px; background: #eef2f7; margin-left: 0.3rem; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 0.75rem; margin: 0 0 0.6rem; }
  dt { font-weight: 600; }
  dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
  .countdown { color: #1a5fb4; font-weight: 600; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
  .button { display: inline-block; padding: 0.2rem 0.6rem; border: 1px solid #767676; border-radius: 3px; background: #efefef; color: inherit; text-decoration: none; font-size: 0.9rem; }
  .notes { display: flex; flex-direction: column; gap: 0.75rem; }
  .danger { color: #b3261e; margin-top: 0.5rem; }
</style>
