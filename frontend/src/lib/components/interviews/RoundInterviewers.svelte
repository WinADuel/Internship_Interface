<script lang="ts">
  import { createContact } from "../../api/contacts";
  import { showToast } from "../../stores/toast";
  import type { Contact } from "../../types/contact";
  import type { RoundContact } from "../../types/interview";

  /** `save` replaces the round's linked interviewers; it rejects when that fails. */
  let {
    applicationId,
    company,
    linked,
    appContacts,
    save,
  }: {
    applicationId: number;
    company: string;
    linked: RoundContact[];
    appContacts: Contact[];
    save: (contactIds: number[]) => Promise<void>;
  } = $props();

  let busy = $state(false);
  let creating = $state(false);
  let name = $state("");
  let title = $state("");
  let email = $state("");
  let error = $state("");
  // Created, but linking it failed: Save retries only the link, so a retry
  // can't add the same person twice.
  let unlinked = $state<Contact | null>(null);

  const linkedIds = $derived(new Set(linked.map((c) => c.id)));
  const available = $derived(appContacts.filter((c) => !c.archived && !linkedIds.has(c.id)));

  async function replace(ids: number[]): Promise<boolean> {
    busy = true;
    try {
      await save(ids);
      return true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Couldn't update the interviewers.");
      return false;
    } finally {
      busy = false;
    }
  }

  function onPick(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    const id = Number(select.value);
    select.value = "";
    if (id) void replace([...linked.map((c) => c.id), id]);
  }

  function closeForm() {
    creating = false;
    unlinked = null;
    name = title = email = "";
  }

  async function create(event: Event) {
    event.preventDefault();
    error = "";
    if (!unlinked && !name.trim()) {
      error = "Name is required.";
      return;
    }
    busy = true;
    let contact = unlinked;
    if (!contact) {
      try {
        contact = await createContact({
          kind: "company",
          name: name.trim(),
          organization: company,
          title: title.trim() || null,
          email: email.trim() || null,
          applicationId,
        });
      } catch (err) {
        showToast(err instanceof Error ? err.message : "Couldn't add the interviewer.");
        busy = false;
        return;
      }
      unlinked = contact;
    }
    if (await replace([...linked.map((c) => c.id), contact.id])) closeForm();
  }
</script>

<section aria-labelledby="interviewers-heading">
  <h2 id="interviewers-heading">Interviewers</h2>
  {#if linked.length === 0}
    <p class="empty">No interviewers linked. Add them so thank-you notes have an address.</p>
  {:else}
    <ul>
      {#each linked as c (c.id)}
        <li>
          <span class="who">
            <strong>{c.name}</strong>{#if c.title}<span class="muted"> · {c.title}</span>{/if}
            {#if c.email}<span class="email">{c.email}</span>{:else}<span class="muted email">No email address</span>{/if}
          </span>
          <button type="button" class="remove" aria-label={`Remove interviewer ${c.name}`} disabled={busy}
            onclick={() => replace(linked.filter((x) => x.id !== c.id).map((x) => x.id))}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
  <div class="row">
    {#if available.length}
      <select aria-label="Add an interviewer from this application's contacts" onchange={onPick} disabled={busy}>
        <option value="">Add from contacts…</option>
        {#each available as c (c.id)}<option value={c.id}>{c.name}{c.title ? ` — ${c.title}` : ""}</option>{/each}
      </select>
    {/if}
    <button type="button" onclick={() => (creating = true)} disabled={creating}>Add interviewer</button>
  </div>
  {#if creating}
    <form class="new" aria-label="New interviewer" novalidate onsubmit={create}>
      <label>Name <input bind:value={name} maxlength="200" autocomplete="off" disabled={!!unlinked} /></label>
      <label>Title <input bind:value={title} maxlength="200" autocomplete="off" disabled={!!unlinked} /></label>
      <label>Email <input type="email" bind:value={email} maxlength="320" autocomplete="off" disabled={!!unlinked} /></label>
      {#if unlinked}<p class="note" role="status">Saved as a contact, but not linked to this round yet. Save tries the link again.</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <div class="row">
        <button type="submit" disabled={busy}>Save interviewer</button>
        <button type="button" onclick={closeForm}>Cancel</button>
      </div>
    </form>
  {/if}
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  ul { list-style: none; margin: 0 0 0.5rem; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
  li { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
  .who { display: flex; flex-wrap: wrap; gap: 0 0.5rem; min-width: 0; overflow-wrap: anywhere; }
  .muted { color: #666; }
  .email { font-size: 0.85rem; }
  .remove { border: 0; background: none; cursor: pointer; font: inherit; padding: 0 0.3rem; color: #666; }
  .row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.5rem; }
  select { max-width: 100%; min-width: 0; font: inherit; }
  .new { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.6rem; border: 1px solid #ddd; border-radius: 6px; }
  label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; font-weight: 600; }
  input { font: inherit; font-weight: 400; padding: 0.35rem; min-width: 0; }
  .empty { color: #666; font-size: 0.9rem; }
  .error { color: #b3261e; margin: 0; }
  .note { margin: 0; font-size: 0.85rem; color: #666; }
</style>
