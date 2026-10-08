<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../lib/api/client";
  import { getSettings, updateSettings } from "../lib/api/settings";
  import BackupSheetStatus from "../lib/components/settings/BackupSheetStatus.svelte";
  import ClaudeTokens from "../lib/components/settings/ClaudeTokens.svelte";
  import DiscoverySettings from "../lib/components/settings/DiscoverySettings.svelte";
  import { showToast } from "../lib/stores/toast";
  import type { AppSettings } from "../lib/types/contact";

  const PROFILE_PLACEHOLDER =
    "Your background, interests, and what you're looking for — Claude uses this to personalize every draft.";

  let settings = $state<AppSettings | null>(null);
  let outreachProfile = $state("");
  let nudgeUnsentDays = $state(5);
  let nudgeFollowupDays = $state(10);
  let nudgeGoneQuietDays = $state(10);
  let nudgeRepliedStaleDays = $state(14);
  let claudeJobMaxItems = $state(8);
  let saving = $state(false);
  let loadError = $state<string | null>(null);

  function fill(s: AppSettings) {
    settings = s;
    outreachProfile = s.outreachProfile;
    nudgeUnsentDays = s.nudgeUnsentDays;
    nudgeFollowupDays = s.nudgeFollowupDays;
    nudgeGoneQuietDays = s.nudgeGoneQuietDays;
    nudgeRepliedStaleDays = s.nudgeRepliedStaleDays;
    claudeJobMaxItems = s.claudeJobMaxItems;
  }

  async function load() {
    loadError = null;
    try {
      fill(await getSettings());
    } catch (err) {
      loadError = err instanceof ApiError ? err.message : "Couldn't load settings.";
    }
  }

  onMount(() => {
    void load();
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    try {
      fill(
        await updateSettings({
          outreachProfile,
          nudgeUnsentDays,
          nudgeFollowupDays,
          nudgeGoneQuietDays,
          nudgeRepliedStaleDays,
          claudeJobMaxItems,
        }),
      );
      showToast("Settings saved.", "info");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Couldn't save settings.");
    } finally {
      saving = false;
    }
  }
</script>

<h1>Settings</h1>

{#if loadError}
  <p class="error" role="alert">
    Couldn't load settings: {loadError}
    <button type="button" onclick={load}>Retry</button>
  </p>
{/if}

<form aria-label="Outreach settings" onsubmit={save}>
  <label class="block">
    Outreach profile
    <textarea rows="6" maxlength="5000" placeholder={PROFILE_PLACEHOLDER} bind:value={outreachProfile}></textarea>
  </label>

  <fieldset>
    <legend>Nudge timings</legend>
    <label>Unsent draft nudge (days) <input type="number" required min="1" max="90" bind:value={nudgeUnsentDays} /></label>
    <label>Follow-up due after (days) <input type="number" required min="1" max="90" bind:value={nudgeFollowupDays} /></label>
    <label>Gone quiet after (days) <input type="number" required min="1" max="90" bind:value={nudgeGoneQuietDays} /></label>
    <label>
      Unanswered reply nudge (days)
      <input type="number" required min="1" max="90" bind:value={nudgeRepliedStaleDays} />
    </label>
  </fieldset>

  <label>
    Max items per daily run
    <input type="number" required min="1" max="25" bind:value={claudeJobMaxItems} />
  </label>

  <button type="submit" disabled={saving || settings === null}>Save</button>
</form>

{#if settings}
  <!-- Its own form and Save: sends only the discovery fields. -->
  <DiscoverySettings {settings} onsaved={(saved) => (settings = saved)} />
{/if}

<ClaudeTokens />

{#if settings}
  <BackupSheetStatus status={settings} />
{/if}

<style>
  .error { color: #a00; }
  form { display: flex; flex-direction: column; gap: 0.75rem; max-width: 40rem; margin-bottom: 1.5rem; }
  .block textarea { display: block; width: 100%; box-sizing: border-box; margin-top: 0.25rem; }
  fieldset { display: flex; flex-direction: column; gap: 0.5rem; }
  input[type="number"] { width: 5rem; margin-left: 0.5rem; }
  button[type="submit"] { align-self: flex-start; }
</style>
