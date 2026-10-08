<script lang="ts">
  import { ApiError } from "../../api/client";
  import { updateContact } from "../../api/contacts";
  import { ACTIONS_BY_STATUS } from "../../contacts/actions";
  import { GUESS_WARNING, fitsInGmailUrl, gmailComposeUrl } from "../../contacts/gmail";
  import { untrack } from "svelte";
  import { markUndoable, replaceContact, runContactAction } from "../../stores/contacts";
  import { showToast } from "../../stores/toast";
  import type { Contact } from "../../types/contact";

  let { contact, which }: { contact: Contact; which: "draft" | "followup" } = $props();

  const isDraft = $derived(which === "draft");
  const sentAction = $derived(isDraft ? ("sent" as const) : ("followed_up" as const));

  let subject = $state("");
  let body = $state("");
  // What the fields were last loaded from, to tell server changes from user edits.
  let loadedFor: string | null = null;
  let loadedSubject = "";
  let loadedBody = "";
  let saving = $state(false);
  let askSent = $state(false);

  // Load on a new contact; also take a newer server copy (e.g. a follow-up
  // the Claude job just delivered) unless the user has unsaved edits.
  $effect(() => {
    const key = `${contact.id}:${which}`;
    const serverSubject = (isDraft ? contact.draftSubject : contact.followupSubject) ?? "";
    const serverBody = (isDraft ? contact.draftBody : contact.followupBody) ?? "";
    untrack(() => {
      const newContact = loadedFor !== key;
      const serverChanged = serverSubject !== loadedSubject || serverBody !== loadedBody;
      const dirty = subject !== loadedSubject || body !== loadedBody;
      if (!newContact && (!serverChanged || dirty)) return;
      loadedFor = key;
      loadedSubject = subject = serverSubject;
      loadedBody = body = serverBody;
      if (newContact) askSent = false;
    });
  });

  const url = $derived(gmailComposeUrl(contact.email ?? "", subject, body));
  const fits = $derived(fitsInGmailUrl(url));
  const canMarkSent = $derived(ACTIONS_BY_STATUS[contact.status].includes(sentAction));

  async function save() {
    saving = true;
    try {
      const data = isDraft
        ? { draftSubject: subject, draftBody: body }
        : { followupSubject: subject, followupBody: body };
      const updated = await updateContact(contact.id, data);
      loadedSubject = subject;
      loadedBody = body;
      replaceContact(updated);
      showToast("Saved.", "info");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't save the draft.");
    } finally {
      saving = false;
    }
  }

  function openInGmail() {
    if (contact.emailConfidence === "pattern_guess" && !window.confirm(GUESS_WARNING)) return;
    window.open(url, "_blank", "noopener");
    askSent = true;
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      showToast("Copied.", "info");
    } catch {
      showToast("Couldn't copy — select the text and copy it by hand.");
    }
  }

  async function markSent() {
    if (await runContactAction(contact.id, sentAction)) {
      markUndoable(contact.id);
      askSent = false;
    }
  }
</script>

<section class="draft-editor" aria-label={isDraft ? "Email draft" : "Follow-up draft"}>
  <h4>{isDraft ? "Email draft" : "Follow-up draft"}</h4>
  <label>Subject <input type="text" bind:value={subject} /></label>
  <label>Body <textarea rows="8" bind:value={body}></textarea></label>
  <div class="row">
    <button type="button" disabled={saving} onclick={save}>Save</button>
    {#if fits}
      <button type="button" onclick={openInGmail}>Open in Gmail</button>
    {:else}
      <span class="note">Too long for a Gmail link — use Copy and paste it into Gmail.</span>
    {/if}
    <button type="button" onclick={copy}>Copy</button>
  </div>
  {#if askSent && canMarkSent}
    <div class="ask" role="status">
      Did you send it?
      <button type="button" onclick={markSent}>Sent</button>
      <button type="button" onclick={() => (askSent = false)}>Not yet</button>
    </div>
  {/if}
</section>

<style>
  .draft-editor { display: flex; flex-direction: column; gap: 0.4rem; }
  h4 { margin: 0.5rem 0 0; }
  label { display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.85rem; }
  textarea { font: inherit; }
  .row { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
  .note { font-size: 0.8rem; color: #6d3d00; }
  .ask { display: flex; gap: 0.4rem; align-items: center; padding: 0.4rem; background: #fff3c4; border-radius: 6px; }
</style>
