<script lang="ts">
  import { ApiError } from "../../api/client";
  import { archiveContact, getContactHistory, updateContact } from "../../api/contacts";
  import { statusLabel } from "../../contacts/actions";
  import { isSafeHttpUrl } from "../../contacts/links";
  import { formatDateTime } from "../../format";
  import { replaceContact } from "../../stores/contacts";
  import { showToast } from "../../stores/toast";
  import type { Priority } from "../../types/application";
  import type { Contact, ContactHistoryEntry } from "../../types/contact";
  import ContactStatusButtons from "./ContactStatusButtons.svelte";
  import DraftEditor from "./DraftEditor.svelte";
  import NudgeBadge from "./NudgeBadge.svelte";

  let { contact, onarchived }: { contact: Contact; onarchived?: (contact: Contact) => void } = $props();

  const EMAIL_LABELS = { found: "found", pattern_guess: "guessed — may bounce", not_found: "not found" };

  const showFollowup = $derived(
    Boolean(contact.followupBody) || contact.status === "sent" || contact.status === "followed_up",
  );
  const safeSources = $derived(contact.sources.filter((s) => isSafeHttpUrl(s.url)));

  // Notes and priority are edited locally and saved together.
  let notes = $state("");
  let priority = $state<Priority>("medium");
  let loadedFor = $state<number | null>(null);
  $effect(() => {
    if (loadedFor === contact.id) return;
    loadedFor = contact.id;
    notes = contact.notes ?? "";
    priority = contact.priority;
  });

  let history = $state<ContactHistoryEntry[]>([]);
  let historyError = $state(false);
  $effect(() => {
    const id = contact.id;
    void contact.updatedAt; // reload after a status change
    void contact.status;
    let cancelled = false;
    historyError = false;
    getContactHistory(id).then(
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

  let saving = $state(false);
  async function saveNotes() {
    saving = true;
    try {
      replaceContact(await updateContact(contact.id, { notes: notes || null, priority }));
      showToast("Saved.", "info");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      saving = false;
    }
  }

  let archiving = $state(false);
  async function archive() {
    if (archiving || !window.confirm(`Archive ${contact.name}?`)) return;
    archiving = true;
    try {
      const updated = await archiveContact(contact.id);
      replaceContact(updated);
      onarchived?.(updated);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't archive the contact.");
    } finally {
      archiving = false;
    }
  }
</script>

<!-- Research text comes from web pages via Claude: plain interpolation only, never {@html}. -->
<article class="panel">
  <h2>{contact.name}</h2>
  <p class="sub">
    {[contact.title, contact.department, contact.organization].filter(Boolean).join(" · ")}
  </p>
  <NudgeBadge nudge={contact.nudge} />

  <dl>
    <dt>Status</dt>
    <dd>{statusLabel(contact.status, contact.kind)}{contact.closedReason ? ` (${contact.closedReason.replace("_", " ")})` : ""}</dd>
    {#if contact.labName}<dt>Lab</dt><dd>{contact.labName}</dd>{/if}
    <dt>Email</dt>
    <dd>{contact.email ?? "—"} <span class="muted">({EMAIL_LABELS[contact.emailConfidence]})</span></dd>
    {#if isSafeHttpUrl(contact.websiteUrl)}
      <dt>Website</dt>
      <dd><a href={contact.websiteUrl} target="_blank" rel="noopener noreferrer">{contact.websiteUrl}</a></dd>
    {/if}
    {#if isSafeHttpUrl(contact.profileUrl)}
      <dt>Profile</dt>
      <dd><a href={contact.profileUrl} target="_blank" rel="noopener noreferrer">{contact.profileUrl}</a></dd>
    {/if}
  </dl>

  <ContactStatusButtons {contact} />

  {#if contact.relevanceNote}
    <h3>Why this person</h3>
    <p class="text">{contact.relevanceNote}</p>
  {/if}
  {#if contact.researchSummary}
    <h3>Research</h3>
    <p class="text">{contact.researchSummary}</p>
  {/if}
  {#if contact.recentWork}
    <h3>Recent work</h3>
    <p class="text">{contact.recentWork}</p>
  {/if}
  {#if safeSources.length}
    <h3>Sources</h3>
    <ul>
      {#each safeSources as source, i (i)}
        <li><a href={source.url} target="_blank" rel="noopener noreferrer">{source.label || source.url}</a></li>
      {/each}
    </ul>
  {/if}

  <DraftEditor {contact} which="draft" />
  {#if showFollowup}
    <DraftEditor {contact} which="followup" />
  {/if}

  <h3>Notes</h3>
  <textarea aria-label="Notes" rows="3" bind:value={notes}></textarea>
  <label class="inline">
    Priority
    <select bind:value={priority}>
      <option value="low">low</option>
      <option value="medium">medium</option>
      <option value="high">high</option>
    </select>
  </label>
  <div class="row">
    <button type="button" disabled={saving} onclick={saveNotes}>Save notes</button>
    <button type="button" class="danger" disabled={archiving} onclick={archive}>Archive</button>
  </div>

  <h3>Status history</h3>
  {#if historyError}
    <p>Couldn't load history.</p>
  {:else if history.length === 0}
    <p class="muted">No status changes yet.</p>
  {:else}
    <ol class="history">
      {#each history as entry (entry.changedAt + entry.newStatus)}
        <li>
          {entry.oldStatus ? statusLabel(entry.oldStatus, contact.kind) : "New"} → {statusLabel(entry.newStatus, contact.kind)}
          <time>{formatDateTime(entry.changedAt)}</time>
        </li>
      {/each}
    </ol>
  {/if}
</article>

<style>
  .panel { display: flex; flex-direction: column; gap: 0.4rem; }
  h2 { margin: 0; }
  h3 { margin: 0.75rem 0 0.2rem; font-size: 0.95rem; }
  .sub, .muted { color: #555; margin: 0; }
  .text { white-space: pre-wrap; word-break: break-word; margin: 0; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; margin: 0.5rem 0; }
  dt { font-weight: 600; }
  dd { margin: 0; word-break: break-word; }
  textarea { font: inherit; }
  .inline { display: flex; gap: 0.5rem; align-items: center; }
  .row { display: flex; gap: 0.5rem; }
  .danger { color: #b3261e; }
  time { margin-left: 0.5rem; color: #666; font-size: 0.8rem; }
</style>
