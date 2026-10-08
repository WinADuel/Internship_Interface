<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../api/client";
  import { archiveContact, getNeedsAttention, snoozeContact } from "../../api/contacts";
  import { NUDGE_LABELS } from "../../contacts/actions";
  import { contacts, replaceContact, runContactAction } from "../../stores/contacts";
  import { showToast } from "../../stores/toast";
  import type { Contact, ContactAction } from "../../types/contact";
  import ContactDetailPanel from "../contacts/ContactDetailPanel.svelte";
  import ContactStatusButtons from "../contacts/ContactStatusButtons.svelte";

  let items = $state<Contact[]>([]);
  let loaded = $state(false);
  let busy = $state(false);
  let openId = $state<number | null>(null);
  const opened = $derived(openId === null ? null : ($contacts.find((c) => c.id === openId) ?? null));

  async function refresh() {
    try {
      items = await getNeedsAttention();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't load contacts needing attention.");
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    void refresh();
  });

  async function act(work: () => Promise<unknown>) {
    busy = true;
    try {
      await work();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      busy = false;
      await refresh();
    }
  }

  const action = (c: Contact, a: ContactAction) => act(() => runContactAction(c.id, a));
  const snooze = (c: Contact, days: number) => act(async () => replaceContact(await snoozeContact(c.id, days)));
  const skip = (c: Contact) => act(async () => replaceContact(await archiveContact(c.id)));

  function openFollowup(c: Contact) {
    replaceContact(c); // the panel reads the shared store, so edits show up live
    openId = c.id;
  }

  function close() {
    openId = null;
    void refresh();
  }
</script>

<div class="widget">
  {#if loaded && items.length === 0}
    <p class="empty">Nothing needs attention.</p>
  {:else}
    <ul>
      {#each items as c (c.id)}
        <li>
          <div class="who">
            <strong>{c.name}</strong> <span class="org">{c.organization}</span>
            {#if c.nudge}<span class="nudge">{NUDGE_LABELS[c.nudge]}</span>{/if}
          </div>
          <div class="actions">
            {#if c.nudge === "unsent"}
              <ContactStatusButtons contact={c} onchange={() => refresh()} />
              <button type="button" disabled={busy} onclick={() => snooze(c, 3)}>Not yet</button>
              <button type="button" disabled={busy} onclick={() => skip(c)}>Skip</button>
            {:else if c.nudge === "followup_due"}
              <button type="button" onclick={() => openFollowup(c)}>Open follow-up</button>
              <button type="button" disabled={busy} onclick={() => action(c, "followed_up")}>Followed up</button>
            {:else if c.nudge === "gone_quiet"}
              <button type="button" disabled={busy} onclick={() => action(c, "no_response")}>No response</button>
              <button type="button" disabled={busy} onclick={() => snooze(c, 7)}>Wait longer</button>
            {:else if c.nudge === "replied_stale"}
              <ContactStatusButtons contact={c} onchange={() => refresh()} />
            {:else if c.nudge === "meeting_outcome"}
              <button type="button" disabled={busy} onclick={() => action(c, "accepted")}>Accepted</button>
              <button type="button" disabled={busy} onclick={() => action(c, "declined")}>Declined</button>
              <button type="button" disabled={busy} onclick={() => snooze(c, 7)}>Still talking</button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if opened}
  <aside class="detail" aria-label="Contact details">
    <button type="button" class="close" onclick={close}>Close</button>
    <ContactDetailPanel contact={opened} onarchived={close} />
  </aside>
{/if}

<style>
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  li { display: flex; flex-direction: column; gap: 0.25rem; padding-bottom: 0.4rem; border-bottom: 1px solid #eee; font-size: 0.85rem; }
  .org { color: #555; }
  .nudge { display: inline-block; margin-left: 0.25rem; padding: 0.05rem 0.4rem; border-radius: 999px; background: #ffe0b2; color: #6d3d00; font-size: 0.75rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: flex-start; }
  .actions button { font-size: 0.8rem; padding: 0.2rem 0.5rem; }
  .empty { color: #666; font-size: 0.85rem; }
  .detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(30rem, 100%); box-sizing: border-box; overflow-y: auto; padding: 1rem; background: #fff; border-left: 1px solid #ddd; box-shadow: -4px 0 12px rgba(0, 0, 0, 0.1); z-index: 10; }
  .close { float: right; }
</style>
