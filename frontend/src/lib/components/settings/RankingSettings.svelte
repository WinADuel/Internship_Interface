<script lang="ts">
  import { onDestroy, untrack } from "svelte";
  import { ApiError } from "../../api/client";
  import { getTopPicksCount } from "../../api/discovery";
  import { updateSettings } from "../../api/settings";
  import { TOP_PICKS_SCORE } from "../../discovery/format";
  import { splitValidation } from "../../settings/validation";
  import { showToast } from "../../stores/toast";
  import type { AppSettings } from "../../types/contact";
  import type { RankingPrefs, RankingSettings } from "../../types/discovery";
  import ChipInput from "../ChipInput.svelte";

  let { settings, onsaved }: { settings: AppSettings; onsaved?: (settings: AppSettings) => void } = $props();

  const COUNT_DEBOUNCE_MS = 400;
  // Caps from backend `schemas/settings.py`.
  const MAX_KEYWORD_LENGTH = 60;
  const MAX_DAILY_LIMIT = 150;

  type FieldName = `ranking_${string}`;

  // Edited locally from the settings at mount; saving refreshes them. Not reset
  // when the parent saves another form, so unsaved edits survive that.
  let roleKeywords = $state<string[]>([]);
  let skillKeywords = $state<string[]>([]);
  let preferredLocations = $state<string[]>([]);
  let preferredCompanies = $state<string[]>([]);
  let avoidCompanies = $state<string[]>([]);
  let dealbreakerKeywords = $state<string[]>([]);
  let dailyLimit = $state<number | null>(40);

  function fill(s: RankingSettings) {
    roleKeywords = [...s.rankingRoleKeywords];
    skillKeywords = [...s.rankingSkillKeywords];
    preferredLocations = [...s.rankingPreferredLocations];
    preferredCompanies = [...s.rankingPreferredCompanies];
    avoidCompanies = [...s.rankingAvoidCompanies];
    dealbreakerKeywords = [...s.rankingDealbreakerKeywords];
    dailyLimit = s.rankingClaudeDailyLimit;
  }
  untrack(() => fill(settings));

  function prefs(): RankingPrefs {
    return {
      rankingRoleKeywords: [...roleKeywords],
      rankingSkillKeywords: [...skillKeywords],
      rankingPreferredLocations: [...preferredLocations],
      rankingPreferredCompanies: [...preferredCompanies],
      rankingAvoidCompanies: [...avoidCompanies],
      rankingDealbreakerKeywords: [...dealbreakerKeywords],
    };
  }

  // --- live Top picks count -------------------------------------------------------

  let count = $state<number | null>(null);
  let countFailed = $state(false);
  // Bumped on every change; a response is applied only if it is still the latest.
  let latest = 0;

  async function countTopPicks(body: RankingPrefs, request: number) {
    try {
      const n = await getTopPicksCount(body);
      if (request !== latest) return;
      count = n;
      countFailed = false;
    } catch {
      if (request !== latest) return;
      countFailed = true;
    }
  }

  $effect(() => {
    const body = prefs();
    const request = ++latest;
    const timer = setTimeout(() => void countTopPicks(body, request), COUNT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  });

  onDestroy(() => {
    latest += 1; // drop any answer still on its way
  });

  const countText = $derived(
    countFailed
      ? "Couldn't count Top picks."
      : count === null
        ? "Counting Top picks…"
        : `Top picks now: ${count}`,
  );

  // --- save -----------------------------------------------------------------------

  let saving = $state(false);
  let formError = $state<string | null>(null);
  let fieldErrors = $state<Partial<Record<FieldName, string>>>({});

  const FIELDS: ReadonlySet<FieldName> = new Set<FieldName>([
    "ranking_role_keywords",
    "ranking_skill_keywords",
    "ranking_preferred_locations",
    "ranking_preferred_companies",
    "ranking_avoid_companies",
    "ranking_dealbreaker_keywords",
    "ranking_claude_daily_limit",
  ]);

  const limitDescribedBy = $derived(
    fieldErrors.ranking_claude_daily_limit
      ? "ranking-daily-limit-hint ranking-daily-limit-error"
      : "ranking-daily-limit-hint",
  );

  // The chip fields, so a save can first add text typed but not yet added.
  type Chips = ReturnType<typeof ChipInput>;
  let chipInputs = $state<Partial<Record<FieldName, Chips>>>({});

  /** Adds each field's pending text; false if any was refused (each field says why). */
  function commitDrafts(): boolean {
    let ok = true;
    for (const input of Object.values(chipInputs)) {
      if (input && !input.commitDraft()) ok = false;
    }
    return ok;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    formError = null;
    fieldErrors = {};
    if (!commitDrafts()) {
      formError = "Some preferences weren't saved. Fix the fields marked below.";
      return;
    }
    saving = true;
    try {
      const saved = await updateSettings({ ...prefs(), rankingClaudeDailyLimit: dailyLimit as number });
      fill(saved);
      showToast("Ranking preferences saved. The Inbox has been re-scored.", "info");
      onsaved?.(saved);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail)) {
        const { fields, other } = splitValidation(err.detail, FIELDS);
        fieldErrors = fields;
        const lead = Object.keys(fields).length ? ["Some preferences weren't saved. Fix the fields marked below."] : [];
        formError = [...lead, ...other].join(" ") || err.message;
      } else {
        formError = err instanceof ApiError
          ? `Couldn't save ranking preferences: ${err.message}`
          : "Couldn't save ranking preferences.";
      }
    } finally {
      saving = false;
    }
  }
</script>

<section class="ranking" aria-labelledby="ranking-heading">
  <h2 id="ranking-heading">Ranking</h2>
  <p class="muted">
    How Best match orders your Discover Inbox. Every posting gets a 0–100 score from these; the daily Claude run
    also reviews the top of the list. With nothing set, the Inbox stays newest first.
  </p>
  <p class="count" role="status">{countText}</p>
  <p class="muted small">Top picks are Inbox postings scoring {TOP_PICKS_SCORE} or more.</p>

  <form aria-label="Ranking preferences" onsubmit={save}>
    <ChipInput
      label="Role keywords"
      hint="Titles containing one of these score highest."
      placeholder="e.g. machine learning"
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={roleKeywords}
      error={fieldErrors.ranking_role_keywords}
      bind:this={chipInputs.ranking_role_keywords}
    />
    <ChipInput
      label="Skill keywords"
      hint="Each one in the title or category adds a little."
      placeholder="e.g. python"
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={skillKeywords}
      error={fieldErrors.ranking_skill_keywords}
      bind:this={chipInputs.ranking_skill_keywords}
    />
    <ChipInput
      label="Preferred locations"
      hint={'Postings in any of these score higher ("Remote" works).'}
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={preferredLocations}
      error={fieldErrors.ranking_preferred_locations}
      bind:this={chipInputs.ranking_preferred_locations}
    />
    <ChipInput
      label="Preferred companies"
      hint="These score higher; companies on your watchlist do too."
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={preferredCompanies}
      error={fieldErrors.ranking_preferred_companies}
      bind:this={chipInputs.ranking_preferred_companies}
    />
    <ChipInput
      label="Avoid companies"
      hint="Postings from these score 0 and sink to the bottom (still shown)."
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={avoidCompanies}
      error={fieldErrors.ranking_avoid_companies}
      bind:this={chipInputs.ranking_avoid_companies}
    />
    <ChipInput
      label="Dealbreaker keywords"
      hint="A title containing one of these scores 0 and sinks to the bottom (still shown)."
      placeholder="e.g. unpaid"
      maxLength={MAX_KEYWORD_LENGTH}
      bind:items={dealbreakerKeywords}
      error={fieldErrors.ranking_dealbreaker_keywords}
      bind:this={chipInputs.ranking_dealbreaker_keywords}
    />

    <div class="field">
      <label>
        Postings Claude reviews per day
        <input
          type="number"
          required
          min="0"
          max={MAX_DAILY_LIMIT}
          aria-invalid={fieldErrors.ranking_claude_daily_limit ? "true" : undefined}
          aria-describedby={limitDescribedBy}
          bind:value={dailyLimit}
        />
      </label>
      <p class="muted small" id="ranking-daily-limit-hint">
        The highest-scoring Inbox postings it hasn't reviewed yet. 0 turns Claude ranking off.
      </p>
      {#if fieldErrors.ranking_claude_daily_limit}
        <p class="field-error" id="ranking-daily-limit-error">{fieldErrors.ranking_claude_daily_limit}</p>
      {/if}
    </div>

    {#if formError}
      <p class="error" role="alert">{formError}</p>
    {/if}
    <button type="submit" disabled={saving}>Save ranking preferences</button>
  </form>
</section>

<style>
  .ranking { max-width: 40rem; margin-bottom: 1.5rem; }
  .muted { color: #666; }
  .small { font-size: 0.85rem; margin: 0; }
  .count { font-weight: 600; margin-bottom: 0.2rem; }
  form { display: flex; flex-direction: column; gap: 1rem; margin-top: 0.75rem; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  input[type="number"] { width: 5rem; margin-left: 0.5rem; }
  .field-error { margin: 0; color: #b3261e; font-size: 0.85rem; }
  .error { color: #b3261e; margin: 0; overflow-wrap: anywhere; }
  button[type="submit"] { align-self: flex-start; }
</style>
