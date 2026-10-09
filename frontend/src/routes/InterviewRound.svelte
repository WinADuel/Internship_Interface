<script lang="ts">
  import { onMount } from "svelte";
  import { push } from "svelte-spa-router";
  import AfterInterview from "../lib/components/interviews/AfterInterview.svelte";
  import AutosaveText from "../lib/components/interviews/AutosaveText.svelte";
  import CompanyBrief from "../lib/components/interviews/CompanyBrief.svelte";
  import PrepChecklist from "../lib/components/interviews/PrepChecklist.svelte";
  import PrepPrompts from "../lib/components/interviews/PrepPrompts.svelte";
  import RoundForm from "../lib/components/interviews/RoundForm.svelte";
  import RoundInterviewers from "../lib/components/interviews/RoundInterviewers.svelte";
  import RoundStories from "../lib/components/interviews/RoundStories.svelte";
  import { getApplication } from "../lib/api/applications";
  import { ApiError } from "../lib/api/client";
  import { listContacts } from "../lib/api/contacts";
  import { calendarUrl, deleteRound, getRound, updateRound } from "../lib/api/interviews";
  import { getSettings } from "../lib/api/settings";
  import { isSafeHttpUrl } from "../lib/contacts/links";
  import { FORMAT_LABELS, STATE_LABELS, countdown, formatRoundTime, roundName } from "../lib/interviews/format";
  import type { PromptContext } from "../lib/prep/prompts";
  import { showToast } from "../lib/stores/toast";
  import type { Application } from "../lib/types/application";
  import type { Contact } from "../lib/types/contact";
  import type { ChecklistItem, InterviewRoundDetail, InterviewRoundUpdate } from "../lib/types/interview";

  let { params = {} }: { params?: { id?: string } } = $props();

  const id = $derived(Number(params.id));

  let round = $state<InterviewRoundDetail | null>(null);
  let application = $state<Application | null>(null);
  let outreachProfile = $state("");
  let appContacts = $state<Contact[]>([]);
  let status = $state<"loading" | "ready" | "missing" | "failed">("loading");
  let editing = $state(false);
  let deleting = $state(false);

  function loadContacts(applicationId: number) {
    listContacts({ applicationId }).then(
      (rows) => (appContacts = rows),
      () => {},
    );
  }

  $effect(() => {
    const roundId = id;
    let cancelled = false;
    status = "loading";
    round = null;
    application = null;
    appContacts = [];
    editing = false;
    if (!Number.isInteger(roundId) || roundId <= 0) {
      status = "missing";
      return;
    }
    getRound(roundId).then(
      (r) => {
        if (cancelled) return;
        round = r;
        status = "ready";
        // Extras for prompts and the interviewer picker; the page works without them.
        getApplication(r.applicationId).then((a) => !cancelled && (application = a), () => {});
        loadContacts(r.applicationId);
      },
      (err) => {
        if (cancelled) return;
        status = err instanceof ApiError && err.status === 404 ? "missing" : "failed";
      },
    );
    return () => {
      cancelled = true;
    };
  });

  onMount(() => {
    // For the "Tell me about yourself" prompt; a placeholder is used without it.
    getSettings().then((s) => (outreachProfile = s.outreachProfile ?? ""), () => {});
  });

  /** Saves and takes the server's copy of the round; throws on failure. */
  async function patchRaw(data: InterviewRoundUpdate): Promise<void> {
    if (!round) return;
    round = await updateRound(round.id, data);
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

  async function onChecklist(next: ChecklistItem[]) {
    if (!round) return;
    const before = round.checklist;
    round.checklist = next; // optimistic; the response brings ids for new items
    const ok = await patch({ checklist: next.map((i) => (i.id ? i : { label: i.label, done: i.done })) });
    if (!ok && round) round.checklist = before;
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

  const now = $derived(new Date());

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

<p class="back"><a href="#/interviews">← Interview Prep</a></p>

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
        <RoundForm {round} onsaved={(saved) => { round = saved; editing = false; }} oncancel={() => (editing = false)} />
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

    <RoundStories roundId={round.id} linked={round.stories} onchanged={async (r) => { round = r; }} />

    <RoundInterviewers
      roundId={round.id}
      applicationId={round.applicationId}
      company={round.company}
      linked={round.contacts}
      {appContacts}
      onchanged={async (r) => { round = r; loadContacts(r.applicationId); }}
    />

    <CompanyBrief applicationId={round.applicationId} />

    {#if promptContext}<PrepPrompts context={promptContext} />{/if}

    <AfterInterview {round} {appContacts} {patch} saveReflection={(text) => patchRaw({ reflection: text })} />
  </article>
{/if}

<style>
  .back { margin: 0 0 0.5rem; }
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
