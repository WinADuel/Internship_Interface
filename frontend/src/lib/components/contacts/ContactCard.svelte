<script lang="ts">
  import type { Contact, EmailConfidence } from "../../types/contact";
  import ContactStatusButtons from "./ContactStatusButtons.svelte";
  import NudgeBadge from "./NudgeBadge.svelte";

  let {
    contact,
    onopen,
    compact = false,
  }: { contact: Contact; onopen?: (contact: Contact) => void; compact?: boolean } = $props();

  const EMAIL_BADGES: Record<EmailConfidence, string> = {
    found: "Email found",
    pattern_guess: "Email guessed",
    not_found: "No email",
  };

  const draftReady = $derived(Boolean(contact.draftBody) && contact.status === "to_contact");

  function onDragStart(event: DragEvent) {
    event.dataTransfer?.setData("text/plain", String(contact.id));
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  }
</script>

<!-- All contact text is plain interpolation: it can come from web pages via Claude. -->
<article class="card" draggable="true" ondragstart={onDragStart}>
  <button type="button" class="open" onclick={() => onopen?.(contact)}>
    <strong>{contact.name}</strong>
  </button>
  <span>{contact.organization}</span>
  {#if contact.title}<span class="muted">{contact.title}</span>{/if}
  <div class="badges">
    <span class="badge {contact.emailConfidence}">{EMAIL_BADGES[contact.emailConfidence]}</span>
    {#if draftReady}<span class="badge draft">Draft ready</span>{/if}
    <NudgeBadge nudge={contact.nudge} />
  </div>
  {#if !compact}
    <ContactStatusButtons {contact} />
  {/if}
</article>

<style>
  .card { display: flex; flex-direction: column; gap: 0.25rem; padding: 0.6rem; background: #fff; border: 1px solid #ddd; border-radius: 6px; cursor: grab; }
  .open { all: unset; cursor: pointer; text-align: left; }
  .open:focus-visible { outline: 2px solid #1a5fb4; }
  .open:hover strong { text-decoration: underline; }
  .muted { font-size: 0.8rem; color: #555; }
  .badges { display: flex; flex-wrap: wrap; gap: 0.25rem; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; background: #e0e0e0; }
  .found { background: #c8e6c9; }
  .pattern_guess { background: #fff3c4; }
  .draft { background: #bbdefb; }
</style>
