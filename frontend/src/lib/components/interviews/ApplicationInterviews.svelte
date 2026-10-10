<script lang="ts">
  import { onMount } from "svelte";
  import { getApplication } from "../../api/applications";
  import { listRounds } from "../../api/interviews";
  import { STATE_LABELS, formatRoundTime, roundName, sortByDate } from "../../interviews/format";
  import { moveApplicationStatus, upsertApplication } from "../../stores/applications";
  import { showToast } from "../../stores/toast";
  import type { Application, ApplicationStatus } from "../../types/application";
  import type { InterviewRoundListItem } from "../../types/interview";
  import RoundForm from "./RoundForm.svelte";

  let { application }: { application: Application } = $props();

  // Statuses before Interview: adding a round offers to move the application on (spec §2).
  const BEFORE_INTERVIEW: ApplicationStatus[] = ["wishlist", "applied", "phone_screen"];

  let rounds = $state<InterviewRoundListItem[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let adding = $state(false);
  let moving = $state(false);

  async function load() {
    try {
      rounds = sortByDate(await listRounds({ applicationId: application.id, scope: "all" }));
      failed = false;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    void load();
  });

  async function onAdded() {
    adding = false;
    await load();
    // The application's next interview is derived from its rounds on the server.
    try {
      upsertApplication(await getApplication(application.id));
    } catch {
      // the list above is already right; the panel's date catches up on the next load
    }
  }

  async function moveToInterview() {
    moving = true;
    try {
      await moveApplicationStatus(application.id, "interview");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't change the status.");
    } finally {
      moving = false;
    }
  }

  const offerMove = $derived(rounds.length > 0 && BEFORE_INTERVIEW.includes(application.status));
</script>

<section class="app-interviews" aria-label="Interviews">
  <div class="head">
    <h3>Interviews</h3>
    <button type="button" onclick={() => (adding = true)} disabled={adding}>Add round</button>
  </div>
  {#if adding}
    <RoundForm applicationId={application.id} onsaved={onAdded} oncancel={() => (adding = false)} />
  {/if}
  {#if failed}
    <p class="empty">Couldn't load this application's interviews.</p>
  {:else if loaded && rounds.length === 0}
    <p class="empty">No interview rounds yet.</p>
  {:else}
    <ul>
      {#each rounds as r (r.id)}
        <li>
          <a href="#/interviews/{r.id}">{roundName(r)}</a>
          <span class="when">{r.scheduledAt ? formatRoundTime(r.scheduledAt) : "Not scheduled"}</span>
          <span class="state">{STATE_LABELS[r.state]}</span>
        </li>
      {/each}
    </ul>
  {/if}
  {#if offerMove}
    <button type="button" class="move" disabled={moving} onclick={moveToInterview}>Move to Interview</button>
  {/if}
</section>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  h3 { margin: 0.75rem 0 0.3rem; }
  ul { list-style: none; padding: 0; margin: 0 0 0.4rem; display: flex; flex-direction: column; gap: 0.25rem; }
  li { display: flex; flex-wrap: wrap; gap: 0 0.5rem; font-size: 0.9rem; overflow-wrap: anywhere; }
  .when, .state { color: #555; font-size: 0.85rem; }
  .empty { color: #666; font-size: 0.85rem; }
  .move { margin-top: 0.2rem; }
</style>
