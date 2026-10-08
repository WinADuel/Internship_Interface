<script lang="ts">
  import { onDestroy } from "svelte";
  import { ApiError } from "../../api/client";
  import { undoContactAction } from "../../api/contacts";
  import { ACTION_LABELS, ACTIONS_BY_STATUS } from "../../contacts/actions";
  import { dateInputToIso, datetimeInputToIso } from "../../contacts/dates";
  import {
    clearUndoable,
    markUndoable,
    replaceContact,
    runContactAction,
    undoDeadlines,
  } from "../../stores/contacts";
  import { showToast } from "../../stores/toast";
  import type { Contact, ContactAction } from "../../types/contact";

  let { contact, onchange }: { contact: Contact; onchange?: (updated: Contact) => void } = $props();

  const actions = $derived(ACTIONS_BY_STATUS[contact.status]);

  let busy = $state(false);
  let showDate = $state(false);
  let actualDate = $state("");
  let askingMeeting = $state(false);
  let meetingAt = $state("");

  // Undo stays visible until the deadline in the shared store passes.
  let now = $state(Date.now());
  const deadline = $derived($undoDeadlines[contact.id] ?? 0);
  const canUndo = $derived(deadline > now);
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    clearTimeout(timer);
    const remaining = deadline - Date.now();
    if (remaining > 0) timer = setTimeout(() => (now = Date.now()), remaining);
    now = Date.now();
  });
  onDestroy(() => clearTimeout(timer));

  async function run(action: ContactAction) {
    if (action === "meeting_set" && !askingMeeting) {
      askingMeeting = true;
      return;
    }
    const meetingIso = action === "meeting_set" ? datetimeInputToIso(meetingAt) : undefined;
    if (action === "meeting_set" && !meetingIso) {
      showToast("Pick the meeting date and time first.");
      return;
    }
    busy = true;
    try {
      const updated = await runContactAction(contact.id, action, {
        on: showDate ? dateInputToIso(actualDate) : undefined,
        meetingAt: meetingIso,
      });
      if (updated) {
        markUndoable(contact.id);
        showDate = false;
        actualDate = "";
        askingMeeting = false;
        meetingAt = "";
        onchange?.(updated);
      }
    } finally {
      busy = false;
    }
  }

  async function undo() {
    busy = true;
    try {
      const updated = await undoContactAction(contact.id);
      clearUndoable(contact.id);
      replaceContact(updated);
      onchange?.(updated);
    } catch (err) {
      clearUndoable(contact.id);
      showToast(err instanceof ApiError ? err.message : "Couldn't undo.");
    } finally {
      busy = false;
    }
  }
</script>

<div class="status-buttons">
  {#if actions.length}
    <div class="row">
      {#each actions as action (action)}
        <button type="button" disabled={busy} onclick={() => run(action)}>{ACTION_LABELS[action]}</button>
      {/each}
    </div>
    {#if askingMeeting}
      <label class="small">
        Meeting time
        <input type="datetime-local" bind:value={meetingAt} required />
      </label>
      <div class="row">
        <button type="button" disabled={busy || !meetingAt} onclick={() => run("meeting_set")}>Save meeting</button>
        <button type="button" class="link" onclick={() => (askingMeeting = false)}>Cancel</button>
      </div>
    {/if}
    {#if showDate}
      <label class="small">
        It was actually on
        <input type="date" bind:value={actualDate} />
      </label>
    {:else}
      <button type="button" class="link small" onclick={() => (showDate = true)}>It was actually on…</button>
    {/if}
  {/if}
  {#if canUndo}
    <button type="button" class="undo" disabled={busy} onclick={undo}>Undo</button>
  {/if}
</div>

<style>
  .status-buttons { display: flex; flex-direction: column; gap: 0.3rem; align-items: flex-start; }
  .row { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  button { font-size: 0.8rem; padding: 0.2rem 0.5rem; }
  .link { background: none; border: none; color: #1a5fb4; padding: 0; cursor: pointer; text-decoration: underline; }
  .small { font-size: 0.75rem; display: flex; flex-direction: column; gap: 0.15rem; }
  .undo { background: #fff3c4; }
</style>
