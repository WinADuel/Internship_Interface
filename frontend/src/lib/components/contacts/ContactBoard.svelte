<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../api/client";
  import { moveContactStatus } from "../../api/contacts";
  import { STATUS_ORDER, statusLabel } from "../../contacts/actions";
  import { contacts, loadContacts, replaceContact } from "../../stores/contacts";
  import { showToast } from "../../stores/toast";
  import type { Contact, ContactKind, ContactStatus } from "../../types/contact";
  import ContactCard from "./ContactCard.svelte";

  let { onopen }: { onopen?: (contact: Contact) => void } = $props();

  let filterKind = $state<ContactKind | undefined>(undefined);

  const FILTERS: Array<[string, ContactKind | undefined]> = [
    ["Professors", "professor"],
    ["Company", "company"],
    ["All", undefined],
  ];

  async function load(kind: ContactKind | undefined) {
    filterKind = kind;
    try {
      await loadContacts(kind);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't load contacts.");
    }
  }

  onMount(() => {
    void load(undefined);
  });

  const visible = $derived(
    $contacts.filter((c) => !c.archived && (filterKind === undefined || c.kind === filterKind)),
  );
  const columns = $derived(
    STATUS_ORDER.map((status) => ({ status, items: visible.filter((c) => c.status === status) })),
  );

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  }

  async function onDrop(event: DragEvent, status: ContactStatus) {
    event.preventDefault();
    const raw = event.dataTransfer?.getData("text/plain") ?? "";
    if (!/^\d+$/.test(raw.trim())) return;
    const id = Number(raw);
    if ($contacts.find((c) => c.id === id)?.status === status) return;
    try {
      replaceContact(await moveContactStatus(id, status));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't move the contact.");
    }
  }
</script>

<div class="filters" role="group" aria-label="Contact type">
  {#each FILTERS as [label, kind] (label)}
    <button type="button" aria-pressed={filterKind === kind} onclick={() => load(kind)}>{label}</button>
  {/each}
</div>

<div class="board">
  {#each columns as column (column.status)}
    {@const title = statusLabel(column.status, filterKind ?? "professor")}
    <section class="column" aria-label={title} ondragover={onDragOver} ondrop={(e) => onDrop(e, column.status)}>
      <h2>{title} ({column.items.length})</h2>
      {#each column.items as contact (contact.id)}
        <ContactCard {contact} {onopen} />
      {/each}
    </section>
  {/each}
</div>

<style>
  .filters { display: flex; gap: 0.4rem; margin-bottom: 0.75rem; }
  .filters button[aria-pressed="true"] { background: #1a5fb4; color: #fff; }
  .board { display: flex; gap: 0.75rem; overflow-x: auto; align-items: flex-start; }
  .column { flex: 1 0 14rem; display: flex; flex-direction: column; gap: 0.5rem; padding: 0.5rem; background: #f4f4f6; border-radius: 8px; min-height: 8rem; }
  h2 { font-size: 0.95rem; margin: 0; }

  @media (max-width: 700px) {
    .board { scroll-snap-type: x proximity; padding-bottom: 0.5rem; -webkit-overflow-scrolling: touch; }
    .column { flex: 0 0 min(80vw, 16rem); scroll-snap-align: start; }
  }
</style>
