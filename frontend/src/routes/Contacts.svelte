<script lang="ts">
  import { ApiError } from "../lib/api/client";
  import { createContact } from "../lib/api/contacts";
  import ContactBoard from "../lib/components/contacts/ContactBoard.svelte";
  import ContactDetailPanel from "../lib/components/contacts/ContactDetailPanel.svelte";
  import { contacts, replaceContact } from "../lib/stores/contacts";
  import { showToast } from "../lib/stores/toast";
  import type { ContactKind } from "../lib/types/contact";

  let selectedId = $state<number | null>(null);
  let adding = $state(false);
  const selected = $derived($contacts.find((c) => c.id === selectedId) ?? null);

  let kind = $state<ContactKind>("professor");
  let name = $state("");
  let organization = $state("");
  let email = $state("");
  let title = $state("");
  let saving = $state(false);

  function close() {
    selectedId = null;
    adding = false;
  }

  function resetForm() {
    name = organization = email = title = "";
    kind = "professor";
  }

  async function add(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    try {
      const created = await createContact({
        kind,
        name: name.trim(),
        organization: organization.trim(),
        email: email.trim() || null,
        title: title.trim() || null,
      });
      replaceContact(created);
      resetForm();
      adding = false;
      selectedId = created.id;
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't add the contact.");
    } finally {
      saving = false;
    }
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && (selectedId !== null || adding)) close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="header">
  <h1>Contacts</h1>
  <button type="button" onclick={() => ((adding = true), (selectedId = null))}>Add contact</button>
</div>
<ContactBoard onopen={(c) => ((selectedId = c.id), (adding = false))} />

{#if adding}
  <aside class="detail" aria-label="Add contact">
    <button type="button" class="close" onclick={close}>Close</button>
    <h2>Add contact</h2>
    <form onsubmit={add}>
      <label>
        Type
        <select bind:value={kind}>
          <option value="professor">Professor</option>
          <option value="company">Company contact</option>
        </select>
      </label>
      <label>Name <input required bind:value={name} /></label>
      <label>Organization <input required bind:value={organization} /></label>
      <label>Email <input type="email" bind:value={email} /></label>
      <label>Title <input bind:value={title} /></label>
      <button type="submit" disabled={saving}>Add</button>
    </form>
  </aside>
{:else if selected}
  <aside class="detail" aria-label="Contact details">
    <button type="button" class="close" onclick={close}>Close</button>
    {#key selected.id}
      <ContactDetailPanel contact={selected} onarchived={close} />
    {/key}
  </aside>
{/if}

<style>
  .header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(30rem, 100%); box-sizing: border-box; overflow-y: auto; padding: 1rem; background: #fff; border-left: 1px solid #ddd; box-shadow: -4px 0 12px rgba(0, 0, 0, 0.1); z-index: 10; }
  .close { float: right; }
  form { display: flex; flex-direction: column; gap: 0.5rem; }
  label { display: flex; flex-direction: column; gap: 0.15rem; }

  @media (max-width: 700px) {
    .detail { width: 100%; border-left: 0; }
  }
</style>
