<script lang="ts">
  import { onMount } from "svelte";
  import { deleteResume, getApplyProfile, updateApplyProfile, uploadResume } from "../../api/apply";
  import { errorMessage } from "../../api/client";
  import { formatDateTime } from "../../format";
  import { showToast } from "../../stores/toast";
  import type { ApplyProfile, ApplyProfileFields, SavedAnswer } from "../../types/apply";
  import ExtensionTokens from "./ExtensionTokens.svelte";

  type TextKey = Exclude<keyof ApplyProfileFields, "work_authorized" | "needs_sponsorship" | "willing_to_relocate">;

  const GROUPS: Array<{ legend: string; fields: Array<[TextKey, string, string?]> }> = [
    {
      legend: "Contact",
      fields: [
        ["first_name", "First name", "given-name"],
        ["last_name", "Last name", "family-name"],
        ["preferred_name", "Preferred name"],
        ["email", "Email", "email"],
        ["phone", "Phone", "tel"],
        ["city", "City", "address-level2"],
        ["state", "State", "address-level1"],
        ["country", "Country", "country-name"],
      ],
    },
    {
      legend: "Links",
      fields: [
        ["linkedin_url", "LinkedIn URL"],
        ["github_url", "GitHub URL"],
        ["website_url", "Website or portfolio"],
      ],
    },
    {
      legend: "Education and work",
      fields: [
        ["school", "School"],
        ["degree", "Degree (e.g. Bachelor's)"],
        ["major", "Major"],
        ["gpa", "GPA"],
        ["graduation_month", "Graduation month"],
        ["graduation_year", "Graduation year"],
        ["current_company", "Current company"],
        ["how_heard", "How you usually heard about the job"],
        ["pronouns", "Pronouns"],
      ],
    },
  ];
  const YES_NO: Array<[keyof ApplyProfileFields, string]> = [
    ["work_authorized", "Authorized to work in the US"],
    ["needs_sponsorship", "Will need visa sponsorship"],
    ["willing_to_relocate", "Willing to relocate"],
  ];
  // Free text, matched to each form's own options; "decline" picks "I don't wish to answer".
  const DEMOGRAPHIC: Array<[TextKey, string]> = [
    ["gender", "Gender"],
    ["race", "Race or ethnicity"],
    ["hispanic_latino", "Hispanic or Latino"],
    ["veteran", "Protected veteran"],
    ["disability", "Disability"],
    ["lgbtq", "LGBTQ+"],
  ];

  let profile = $state<ApplyProfile | null>(null);
  let fields = $state<ApplyProfileFields | null>(null);
  let saved = $state<SavedAnswer[]>([]);
  let llmUrl = $state("");
  let llmModel = $state("");
  let saving = $state(false);
  let uploading = $state(false);
  let loadError = $state<string | null>(null);

  function fill(p: ApplyProfile) {
    profile = p;
    fields = { ...p.fields };
    saved = p.savedAnswers.map((a) => ({ ...a }));
    llmUrl = p.llmUrl;
    llmModel = p.llmModel;
  }

  async function load() {
    loadError = null;
    try {
      fill(await getApplyProfile());
    } catch (err) {
      loadError = errorMessage(err, "Couldn't load your apply profile.");
    }
  }

  onMount(() => {
    void load();
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!fields) return;
    saving = true;
    try {
      fill(
        await updateApplyProfile({
          fields,
          savedAnswers: saved.filter((a) => a.question.trim()),
          llmUrl,
          llmModel,
        }),
      );
      showToast("Apply profile saved.", "info");
    } catch (err) {
      showToast(errorMessage(err, "Couldn't save your apply profile."));
    } finally {
      saving = false;
    }
  }

  async function onResume(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    uploading = true;
    try {
      const p = await uploadResume(file);
      if (profile) profile = { ...profile, resumeFilename: p.resumeFilename, resumeUploadedAt: p.resumeUploadedAt };
      showToast("Resume uploaded.", "info");
    } catch (err) {
      showToast(errorMessage(err, "Couldn't upload your resume."));
    } finally {
      uploading = false;
      input.value = "";
    }
  }

  async function removeResume() {
    if (!window.confirm("Remove your resume from InternHelper?")) return;
    try {
      const p = await deleteResume();
      if (profile) profile = { ...profile, resumeFilename: p.resumeFilename, resumeUploadedAt: p.resumeUploadedAt };
    } catch (err) {
      showToast(errorMessage(err, "Couldn't remove your resume."));
    }
  }
</script>

<section aria-labelledby="apply-profile-heading" class="apply">
  <h2 id="apply-profile-heading">Apply profile</h2>
  <p class="muted">
    Auto-apply fills Greenhouse, Lever and Ashby applications with these answers. Anything left blank stays blank
    for you to fill on the form. You always review the page and click Submit yourself.
  </p>

  {#if loadError}
    <p class="error" role="alert">{loadError} <button type="button" aria-label="Retry loading the apply profile" onclick={load}>Retry</button></p>
  {/if}

  {#if profile && fields}
    <div class="resume">
      <strong>Resume:</strong>
      {#if profile.resumeFilename}
        {profile.resumeFilename}
        {#if profile.resumeUploadedAt}<span class="muted">(uploaded {formatDateTime(profile.resumeUploadedAt)})</span>{/if}
        <button type="button" onclick={removeResume}>Remove</button>
      {:else}
        <span class="muted">none yet</span>
      {/if}
      <label class="upload">
        {profile.resumeFilename ? "Replace" : "Upload"} (PDF or Word, up to 5 MB)
        <input
          type="file"
          accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={uploading}
          onchange={onResume}
        />
      </label>
    </div>

    <form aria-label="Apply profile" onsubmit={save}>
      {#each GROUPS as group (group.legend)}
        <fieldset>
          <legend>{group.legend}</legend>
          <div class="grid">
            {#each group.fields as [key, label, autocomplete] (key)}
              <label>
                {label}
                <input type="text" maxlength="300" autocomplete={(autocomplete ?? "off") as AutoFill} bind:value={fields[key]} />
              </label>
            {/each}
            {#each group.legend === "Education and work" ? YES_NO : [] as [key, label] (key)}
              <label>
                {label}
                <select bind:value={fields[key]}>
                  <option value="">Leave blank</option>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </label>
            {/each}
          </div>
        </fieldset>
      {/each}

      <fieldset>
        <legend>Voluntary self-identification</legend>
        <p class="muted small">
          Optional. Type your answer the way forms word it (for example "Male", "Asian", "No"), or "decline" to pick
          "I don't wish to answer". Leave it blank to answer on each form yourself.
        </p>
        <div class="grid">
          {#each DEMOGRAPHIC as [key, label] (key)}
            <label>
              {label}
              <input type="text" maxlength="200" list="demographic-suggestions" bind:value={fields[key]} />
            </label>
          {/each}
        </div>
        <datalist id="demographic-suggestions">
          <option value="decline"></option>
          <option value="yes"></option>
          <option value="no"></option>
        </datalist>
      </fieldset>

      <fieldset>
        <legend>Saved answers</legend>
        <p class="muted small">
          Answers reused whenever a form asks the same question. "Reuse this answer" on an application adds one here.
        </p>
        {#each saved as answer, i (i)}
          <div class="saved">
            <label>Question <input type="text" maxlength="500" bind:value={answer.question} /></label>
            <label>Answer <textarea rows="3" maxlength="10000" bind:value={answer.answer}></textarea></label>
            <button type="button" aria-label={`Delete saved answer ${i + 1}`} onclick={() => (saved = saved.filter((_, j) => j !== i))}>
              Delete
            </button>
          </div>
        {/each}
        <button type="button" onclick={() => (saved = [...saved, { question: "", answer: "" }])}>Add an answer</button>
      </fieldset>

      <fieldset>
        <legend>Local AI (optional)</legend>
        <p class="muted small">
          An Ollama model on your own computer drafts answers to open questions like "Why do you want to work here?",
          from your outreach profile above. Leave blank to write them yourself.
        </p>
        <div class="grid">
          <label>Address <input type="text" maxlength="500" placeholder="http://192.168.1.20:11434" bind:value={llmUrl} /></label>
          <label>Model <input type="text" maxlength="200" placeholder="qwen3:14b" bind:value={llmModel} /></label>
        </div>
      </fieldset>

      <button type="submit" disabled={saving}>Save apply profile</button>
    </form>
  {/if}

  <ExtensionTokens />
</section>

<style>
  .apply { max-width: 46rem; margin-bottom: 1.5rem; }
  .muted { color: #666; }
  .small { font-size: 0.85rem; margin: 0 0 0.5rem; }
  .error { color: #a00; }
  .resume { display: flex; flex-wrap: wrap; gap: 0.4rem 0.75rem; align-items: center; margin-bottom: 0.75rem; }
  .upload { display: flex; flex-direction: column; font-size: 0.85rem; }
  form { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1rem; }
  fieldset { display: flex; flex-direction: column; gap: 0.5rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 0.5rem 0.75rem; }
  .grid label { display: flex; flex-direction: column; font-size: 0.9rem; }
  .grid input, .grid select { margin-top: 0.15rem; }
  .saved { display: flex; flex-direction: column; gap: 0.25rem; border-bottom: 1px solid #eee; padding-bottom: 0.5rem; }
  .saved input, .saved textarea { width: 100%; box-sizing: border-box; }
  .saved button, button[type="submit"] { align-self: flex-start; }
</style>
