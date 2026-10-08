<script lang="ts">
  import { ApiError } from "../../api/client";
  import { listContacts } from "../../api/contacts";
  import { findContacts } from "../../api/researchQueue";
  import { showToast } from "../../stores/toast";
  import type { Contact } from "../../types/contact";
  import ContactCard from "./ContactCard.svelte";

  let { applicationId }: { applicationId: number } = $props();

  let items = $state<Contact[]>([]);
  let loaded = $state(false);
  let finding = $state(false);

  $effect(() => {
    const id = applicationId;
    let cancelled = false;
    loaded = false;
    listContacts({ kind: "company", applicationId: id }).then(
      (rows) => {
        if (cancelled) return;
        items = rows;
        loaded = true;
      },
      () => {
        if (cancelled) return;
        loaded = true;
        showToast("Couldn't load this application's contacts.");
      },
    );
    return () => {
      cancelled = true;
    };
  });

  async function find() {
    finding = true;
    try {
      await findContacts(applicationId);
      showToast("Queued — contacts will appear after the daily Claude run.", "info");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) showToast("Contacts already queued for this application.");
      else showToast(err instanceof ApiError ? err.message : "Couldn't queue the search.");
    } finally {
      finding = false;
    }
  }
</script>

<section class="app-contacts" aria-label="Contacts">
  <div class="head">
    <h3>Contacts</h3>
    <button type="button" disabled={finding} onclick={find}>Find contacts</button>
  </div>
  {#if loaded && items.length === 0}
    <p class="empty">No contacts yet — they'll appear after the daily Claude run.</p>
  {:else}
    <div class="list">
      {#each items as contact (contact.id)}
        <ContactCard {contact} compact />
      {/each}
    </div>
  {/if}
  {#if items.length}
    <a href="#/contacts">Open in Contacts</a>
  {/if}
</section>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  h3 { margin: 0.75rem 0 0.3rem; }
  .list { display: flex; flex-direction: column; gap: 0.4rem; }
  .empty { color: #666; font-size: 0.85rem; }
</style>
