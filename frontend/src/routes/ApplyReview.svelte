<script lang="ts">
  import { applyToPosting } from "../lib/api/discovery";
  import { draftWithAi, getApplication, saveAnswers } from "../lib/api/apply";
  import { errorMessage } from "../lib/api/client";
  import { formatDateTime } from "../lib/format";
  import { showToast } from "../lib/stores/toast";
  import type { AnswerSource, AnswerUpdate, ApplyDraft, FormField } from "../lib/types/apply";

  let { params }: { params: { id: string } } = $props();

  const postingId = $derived(Number(params.id));

  let draft = $state<ApplyDraft | null>(null);
  let loadError = $state<string | null>(null);
  let loading = $state(false);
  // The values shown in the inputs, and which text answers to remember.
  let values = $state<Record<string, string | string[]>>({});
  let remember = $state<Record<string, boolean>>({});
  let busy = $state<"" | "save" | "open" | "ai" | "applied">("");

  const SOURCE_LABELS: Record<Exclude<AnswerSource, "">, string> = {
    profile: "From your profile",
    saved: "Saved answer",
    ai: "AI draft: check it",
    you: "Your answer",
  };
  const ATS_LABELS: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };

  function show(d: ApplyDraft) {
    draft = d;
    values = Object.fromEntries(d.fields.map((f) => [f.key, Array.isArray(f.value) ? [...f.value] : f.value]));
    remember = {};
  }

  async function load(refresh = false) {
    loading = true;
    loadError = null;
    try {
      show(await getApplication(postingId, refresh));
    } catch (err) {
      loadError = errorMessage(err, "Couldn't read this posting's application form.");
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (Number.isInteger(postingId) && postingId > 0) void load();
  });

  function same(a: string | string[], b: string | string[]): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  const changes = $derived.by(() => {
    const out: Record<string, AnswerUpdate> = {};
    for (const f of draft?.fields ?? []) {
      if (f.kind === "file") continue;
      const value = values[f.key] ?? "";
      if (!same(value, f.value) || remember[f.key]) out[f.key] = { value, remember: !!remember[f.key] };
    }
    return out;
  });
  const dirty = $derived(Object.keys(changes).length > 0);

  function filled(f: FormField): boolean {
    if (f.kind === "file") return !!f.value;
    const v = values[f.key];
    return Array.isArray(v) ? v.length > 0 : !!v?.trim();
  }

  const counts = $derived.by(() => {
    const fields = draft?.fields ?? [];
    return {
      total: fields.length,
      filled: fields.filter(filled).length,
      missing: fields.filter((f) => f.required && !filled(f)),
      ai: fields.filter((f) => f.source === "ai").length,
    };
  });
  const appFields = $derived((draft?.fields ?? []).filter((f) => f.section !== "demographic"));
  const demoFields = $derived((draft?.fields ?? []).filter((f) => f.section === "demographic"));
  const openEmpty = $derived(appFields.filter((f) => f.kind === "textarea" && !filled(f)).length);

  async function save(): Promise<boolean> {
    if (!draft || !dirty) return true;
    try {
      show(await saveAnswers(draft.postingId, changes));
      return true;
    } catch (err) {
      showToast(errorMessage(err, "Couldn't save your answers."));
      return false;
    }
  }

  async function onSave() {
    busy = "save";
    if (await save()) showToast("Answers saved.", "info");
    busy = "";
  }

  async function openApplication() {
    if (!draft) return;
    // Opened before the save finishes, so the browser doesn't treat it as an unrequested pop-up.
    const tab = window.open("about:blank", "_blank");
    busy = "open";
    const ok = await save();
    busy = "";
    if (!ok) {
      tab?.close();
      return;
    }
    if (tab) {
      tab.opener = null;
      tab.location.href = draft.applyUrl;
    } else {
      window.location.href = draft.applyUrl;
    }
  }

  async function draftAnswers() {
    if (!draft) return;
    busy = "ai";
    try {
      if (!(await save())) return;
      const result = await draftWithAi(draft.postingId);
      show(result.draft);
      if (result.drafted.length) {
        showToast(`Drafted ${result.drafted.length} answer${result.drafted.length === 1 ? "" : "s"}. Read each one before you apply.`, "info");
      }
      if (result.error) showToast(`Local AI: ${result.error}`);
      else if (result.failed.length) {
        showToast(`${result.failed.length} question${result.failed.length === 1 ? "" : "s"} need${result.failed.length === 1 ? "s" : ""} your own answer.`, "info");
      }
    } catch (err) {
      showToast(errorMessage(err, "Couldn't draft answers."));
    } finally {
      busy = "";
    }
  }

  async function markApplied() {
    if (!draft) return;
    busy = "applied";
    try {
      await applyToPosting(draft.postingId);
      draft = { ...draft, postingState: "applied" };
      showToast(`Marked ${draft.company} as applied.`, "info");
    } catch (err) {
      showToast(errorMessage(err, "Couldn't mark it as applied."));
    } finally {
      busy = "";
    }
  }

  function toggle(key: string, label: string, on: boolean) {
    const current = Array.isArray(values[key]) ? (values[key] as string[]) : [];
    values[key] = on ? [...current, label] : current.filter((v) => v !== label);
  }
</script>

<p><a href="#/discover">← Discover</a></p>

{#if loadError}
  <h1>Prepare application</h1>
  <p class="error" role="alert">{loadError}</p>
  <button type="button" onclick={() => load()}>Try again</button>
{:else if !draft}
  <h1>Prepare application</h1>
  <p class="muted">{loading ? "Reading the application form…" : ""}</p>
{:else}
  <h1>{draft.company}: {draft.title}</h1>
  <p class="muted">
    Form read from {ATS_LABELS[draft.ats] ?? draft.ats} on {formatDateTime(draft.fetchedAt)}.
    <button type="button" class="link" disabled={loading} onclick={() => load(true)}>Read it again</button>
  </p>

  <div class="summary" aria-live="polite">
    <strong>{counts.filled} of {counts.total} filled.</strong>
    {#if counts.missing.length}
      <span class="warn">{counts.missing.length} required still empty.</span>
    {/if}
    {#if counts.ai}<span class="ai-note">{counts.ai} drafted by AI: read them before you apply.</span>{/if}
    {#if !draft.resumeFilename}
      <span class="warn">No resume uploaded. Add it in <a href="#/settings">Settings</a>.</span>
    {/if}
  </div>

  <div class="actions">
    <button type="button" onclick={onSave} disabled={!dirty || busy !== ""}>Save</button>
    <button type="button" class="primary" onclick={openApplication} disabled={busy !== ""}>
      {dirty ? "Save and open application" : "Open application"}
    </button>
    {#if draft.llmReady}
      <button type="button" onclick={draftAnswers} disabled={busy !== "" || openEmpty === 0}>
        {busy === "ai" ? "Drafting…" : "Draft empty answers with local AI"}
      </button>
    {/if}
    {#if draft.postingState !== "applied"}
      <button type="button" onclick={markApplied} disabled={busy !== ""}>Mark as applied</button>
    {:else}
      <span class="badge done">Applied</span>
    {/if}
  </div>
  <p class="muted small">
    Open application opens the company's real form. The InternHelper extension fills it with these answers;
    check the page and click Submit yourself. InternHelper never submits for you.
  </p>

  {#snippet fieldRow(f: FormField)}
    <div class="field" class:missing={f.required && !filled(f)}>
      <div class="label-row">
        <label for={`f-${f.key}`} class="q">
          {f.label}{#if f.required}<span class="req" aria-label="required"> *</span>{/if}
        </label>
        {#if f.source}<span class="badge src-{f.source}">{SOURCE_LABELS[f.source]}</span>{/if}
      </div>
      {#if f.description}<p class="desc">{f.description}</p>{/if}

      {#if f.kind === "textarea"}
        <textarea id={`f-${f.key}`} rows="5" maxlength="10000" bind:value={values[f.key] as string}></textarea>
        <label class="remember">
          <input type="checkbox" bind:checked={remember[f.key]} /> Reuse this answer for the same question on other applications
        </label>
      {:else if f.kind === "text"}
        <input id={`f-${f.key}`} type="text" maxlength="10000" bind:value={values[f.key] as string} />
      {:else if f.kind === "select" || f.kind === "boolean"}
        <select id={`f-${f.key}`} bind:value={values[f.key] as string}>
          <option value="">Leave blank</option>
          {#if f.kind === "boolean"}
            <option value="Yes">Yes</option>
            <option value="No">No</option>
          {:else}
            {#each f.options as option, i (i)}<option value={option.label}>{option.label}</option>{/each}
          {/if}
        </select>
      {:else if f.kind === "multiselect"}
        <fieldset id={`f-${f.key}`} class="checks">
          <legend class="visually-hidden">{f.label}</legend>
          {#each f.options as option, i (i)}
            <label>
              <input
                type="checkbox"
                checked={(values[f.key] as string[] | undefined)?.includes(option.label) ?? false}
                onchange={(e) => toggle(f.key, option.label, e.currentTarget.checked)}
              />
              {option.label}
            </label>
          {/each}
        </fieldset>
      {:else if f.kind === "file"}
        <p id={`f-${f.key}`} class="file">
          {#if f.value}Attaches <strong>{f.value}</strong>{:else}Attach this on the page yourself.{/if}
        </p>
      {/if}
    </div>
  {/snippet}

  <section aria-labelledby="questions-heading">
    <h2 id="questions-heading">Application</h2>
    {#each appFields as f (f.key)}{@render fieldRow(f)}{/each}
  </section>

  {#if demoFields.length}
    <section aria-labelledby="demographic-heading">
      <h2 id="demographic-heading">Voluntary self-identification</h2>
      <p class="muted small">Optional questions. Set your answers once in Settings › Apply profile.</p>
      {#each demoFields as f (f.key)}{@render fieldRow(f)}{/each}
    </section>
  {/if}
{/if}

<style>
  .error { color: #a00; }
  .muted { color: #555; }
  .small { font-size: 0.85rem; }
  .link { background: none; border: none; color: #1a5fb4; cursor: pointer; padding: 0; text-decoration: underline; }
  .summary { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; margin: 0.5rem 0; }
  .warn { color: #8a4b00; }
  .ai-note { color: #6b3fa0; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: 0.75rem 0 0.25rem; }
  .primary { font-weight: 600; }
  section { max-width: 46rem; margin-top: 1.25rem; }
  .field { border: 1px solid #ddd; border-radius: 6px; padding: 0.6rem; margin-bottom: 0.6rem; background: #fff; }
  .field.missing { border-color: #e0a100; background: #fffbea; }
  .label-row { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.4rem; align-items: baseline; }
  .q { font-weight: 600; overflow-wrap: anywhere; }
  .req { color: #a00; }
  .desc { margin: 0.2rem 0; font-size: 0.85rem; color: #555; overflow-wrap: anywhere; }
  textarea, input[type="text"], select { display: block; width: 100%; box-sizing: border-box; margin-top: 0.35rem; }
  .remember { display: block; font-size: 0.8rem; color: #555; margin-top: 0.25rem; }
  .checks { border: none; padding: 0; margin: 0.35rem 0 0; display: flex; flex-direction: column; gap: 0.2rem; }
  .file { margin: 0.35rem 0 0; }
  .badge { display: inline-block; padding: 0.05rem 0.45rem; border-radius: 999px; font-size: 0.75rem; background: #e0e0e0; color: #222; }
  .src-profile, .src-saved { background: #e8eef7; color: #1a3d6d; }
  .src-ai { background: #efe3fb; color: #4b2380; }
  .src-you { background: #d7f0dc; color: #14532d; }
  .done { background: #d7f0dc; color: #14532d; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
