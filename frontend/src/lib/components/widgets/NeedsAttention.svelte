<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import { portal } from "../../actions/portal";
  import { errorMessage } from "../../api/client";
  import { archiveContact, getNeedsAttention, snoozeContact, undoContactAction } from "../../api/contacts";
  import { NUDGE_LABELS, statusLabel } from "../../contacts/actions";
  import {
    clearUndoable,
    contacts,
    markUndoable,
    replaceContact,
    runContactAction,
    undoDeadlines,
  } from "../../stores/contacts";
  import { emailStatus, refreshEmailStatus } from "../../stores/email";
  import { showToast } from "../../stores/toast";
  import type { Contact, ContactAction } from "../../types/contact";
  import ContactDetailPanel from "../contacts/ContactDetailPanel.svelte";
  import ContactStatusButtons from "../contacts/ContactStatusButtons.svelte";

  let items = $state<Contact[]>([]);
  let loaded = $state(false);
  let loadFailed = $state(false);
  let busy = $state(false);
  let openId = $state<number | null>(null);
  let opener: HTMLElement | null = null;
  let closeButton = $state<HTMLButtonElement | null>(null);
  const opened = $derived(openId === null ? null : ($contacts.find((c) => c.id === openId) ?? null));

  // Status changes made here drop off the list once the nudge clears, so keep
  // a "Marked …" row with Undo until the 60 s window closes (spec §13.3).
  let acted = $state<Record<number, Contact>>({});
  const expiry = new Map<number, ReturnType<typeof setTimeout>>();
  const settled = $derived(
    Object.values(acted).filter((c) => !items.some((i) => i.id === c.id) && ($undoDeadlines[c.id] ?? 0) > 0),
  );

  function forget(id: number) {
    clearTimeout(expiry.get(id));
    expiry.delete(id);
    delete acted[id];
  }

  function remember(updated: Contact) {
    const deadline = $undoDeadlines[updated.id];
    if (!deadline) {
      forget(updated.id);
      return;
    }
    acted[updated.id] = updated;
    clearTimeout(expiry.get(updated.id));
    expiry.set(updated.id, setTimeout(() => forget(updated.id), Math.max(0, deadline - Date.now()) + 1));
  }

  onDestroy(() => expiry.forEach((t) => clearTimeout(t)));

  async function refresh() {
    try {
      items = await getNeedsAttention();
      loadFailed = false;
    } catch (err) {
      loadFailed = true;
      showToast(errorMessage(err, "Couldn't load contacts needing attention."));
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    void refresh();
    void refreshEmailStatus();
  });

  const emailCount = $derived($emailStatus?.pendingCount ?? 0);

  async function act(work: () => Promise<unknown>) {
    busy = true;
    try {
      await work();
    } catch (err) {
      showToast(errorMessage(err, "Something went wrong."));
    } finally {
      busy = false;
      await refresh();
    }
  }

  const action = (c: Contact, a: ContactAction) =>
    act(async () => {
      const updated = await runContactAction(c.id, a);
      if (updated) {
        markUndoable(c.id);
        remember(updated);
      }
    });
  const snooze = (c: Contact, days: number) => act(async () => replaceContact(await snoozeContact(c.id, days)));
  const skip = (c: Contact) => act(async () => replaceContact(await archiveContact(c.id)));

  function changed(updated: Contact) {
    remember(updated);
    void refresh();
  }

  const undo = (c: Contact) =>
    act(async () => {
      try {
        replaceContact(await undoContactAction(c.id));
      } finally {
        clearUndoable(c.id);
        forget(c.id);
      }
    });

  async function openFollowup(c: Contact, event: MouseEvent) {
    opener = event.currentTarget as HTMLElement;
    replaceContact(c); // the panel reads the shared store, so edits show up live
    openId = c.id;
    await tick();
    closeButton?.focus();
  }

  function close() {
    openId = null;
    opener?.focus();
    opener = null;
    void refresh();
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && openId !== null) close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="widget">
  {#if emailCount > 0}
    <a class="email" href="#/email">
      {emailCount} email {emailCount === 1 ? "update" : "updates"} to review
    </a>
  {/if}
  {#if loadFailed && items.length === 0 && settled.length === 0}
    <p class="empty">Couldn't load contacts needing attention.</p>
  {:else if loaded && items.length === 0 && settled.length === 0}
    {#if emailCount === 0}<p class="empty">Nothing needs attention.</p>{/if}
  {:else}
    <ul>
      {#each items as c (c.id)}
        <li role="group" aria-labelledby={`na-name-${c.id}`}>
          <div class="who">
            <strong id={`na-name-${c.id}`}>{c.name}</strong> <span class="org">{c.organization}</span>
            {#if c.nudge}<span class="nudge">{NUDGE_LABELS[c.nudge]}</span>{/if}
          </div>
          <fieldset class="actions" disabled={busy}>
            {#if c.nudge === "unsent"}
              <ContactStatusButtons contact={c} onchange={changed} />
              <button type="button" onclick={() => snooze(c, 3)}>Not yet</button>
              <button type="button" onclick={() => skip(c)}>Skip</button>
            {:else if c.nudge === "followup_due"}
              <button type="button" onclick={(e) => openFollowup(c, e)}>Open follow-up</button>
              <button type="button" onclick={() => action(c, "followed_up")}>Followed up</button>
            {:else if c.nudge === "gone_quiet"}
              <button type="button" onclick={() => action(c, "no_response")}>No response</button>
              <button type="button" onclick={() => snooze(c, 7)}>Wait longer</button>
            {:else if c.nudge === "replied_stale"}
              <ContactStatusButtons contact={c} onchange={changed} />
            {:else if c.nudge === "meeting_outcome"}
              <button type="button" onclick={() => action(c, "accepted")}>Accepted</button>
              <button type="button" onclick={() => action(c, "declined")}>Declined</button>
              <button type="button" onclick={() => snooze(c, 7)}>Still talking</button>
            {/if}
            {#if acted[c.id] && c.nudge !== "unsent" && c.nudge !== "replied_stale"}
              <!-- Acted on here but still listed (e.g. Sent with an old date is now follow-up due). -->
              <button type="button" class="undo" onclick={() => undo(c)}>Undo</button>
            {/if}
          </fieldset>
        </li>
      {/each}
      {#each settled as c (c.id)}
        <li class="settled" role="group" aria-labelledby={`na-done-${c.id}`}>
          <span id={`na-done-${c.id}`}><strong>{c.name}</strong>: marked {statusLabel(c.status, c.kind)}.</span>
          <fieldset class="actions" disabled={busy}>
            <button type="button" class="undo" onclick={() => undo(c)}>Undo</button>
          </fieldset>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if opened}
  <aside class="detail" aria-label="Contact details" use:portal>
    <button type="button" class="close" bind:this={closeButton} onclick={close}>Close</button>
    {#key opened.id}
      <ContactDetailPanel contact={opened} onarchived={close} />
    {/key}
  </aside>
{/if}

<style>
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; }
  li { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.6rem 0; border-top: 1px solid var(--border); font-size: 0.85rem; }
  li:first-child { border-top: 0; padding-top: 0.1rem; }
  .settled { color: var(--muted-foreground); }
  .org { color: var(--muted-foreground); }
  .nudge { display: inline-block; margin-left: 0.3rem; padding: 0.05rem 0.45rem; border-radius: var(--radius-sm); border: 1px solid color-mix(in oklch, var(--warning) 35%, transparent); color: var(--warning); font-size: 0.72rem; font-weight: 500; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: flex-start; border: 0; margin: 0; padding: 0; min-width: 0; }
  .actions button { font-size: 0.78rem; padding: 0.2rem 0.6rem; }
  .undo { border-color: color-mix(in oklch, var(--warning) 40%, transparent); }
  .empty { color: var(--muted-foreground); font-size: 0.85rem; margin: 0; }
  .email { display: flex; align-items: center; margin-bottom: 0.6rem; padding: 0.45rem 0.65rem; border-radius: var(--radius-md); border: 1px solid color-mix(in oklch, var(--info) 25%, transparent); background: color-mix(in srgb, var(--info) 6%, var(--background)); color: var(--info); font-size: 0.82rem; font-weight: 600; }
  .email:hover { text-decoration: none; background: color-mix(in srgb, var(--info) 10%, var(--background)); }
  .detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(30rem, 100%); box-sizing: border-box; overflow-y: auto; padding: 1rem; background: var(--background); border-left: 1px solid var(--border); box-shadow: -8px 0 24px rgb(0 0 0 / 0.08); z-index: 30; }
  .close { float: right; }
</style>
