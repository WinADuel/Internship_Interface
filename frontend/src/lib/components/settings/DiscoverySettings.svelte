<script lang="ts">
  import { onDestroy, untrack } from "svelte";
  import { ApiError } from "../../api/client";
  import { getMatchCount } from "../../api/discovery";
  import { updateSettings } from "../../api/settings";
  import { showToast } from "../../stores/toast";
  import type { AppSettings } from "../../types/contact";
  import type { DiscoveryFilters, DiscoverySettings } from "../../types/discovery";
  import ChipInput from "./ChipInput.svelte";

  let { settings, onsaved }: { settings: AppSettings; onsaved?: (settings: AppSettings) => void } = $props();

  /** The five Simplify categories (backend `parsers._CATEGORY_ALIASES`). */
  const CATEGORY_SUGGESTIONS = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"];
  const COUNT_DEBOUNCE_MS = 400;
  // Caps from backend `schemas/settings.py`.
  const MAX_URLS = 10;
  const MAX_URL_LENGTH = 500;

  type Field = keyof DiscoverySettings;
  type FieldName = `discovery_${string}`;

  // Edited locally from the settings at mount; saving refreshes them. Not reset
  // when the parent saves its other form, so unsaved filter edits survive that.
  let terms = $state<string[]>([]);
  let categories = $state<string[]>([]);
  let includeKeywords = $state<string[]>([]);
  let watchlistKeywords = $state<string[]>([]);
  let excludeKeywords = $state<string[]>([]);
  let locations = $state<string[]>([]);
  let hideNoSponsorship = $state(false);
  let scanHours = $state<number | null>(6);
  let listUrls = $state<string[]>([]);

  function fill(s: DiscoverySettings) {
    terms = [...s.discoveryTerms];
    categories = [...s.discoveryCategories];
    includeKeywords = [...s.discoveryIncludeKeywords];
    watchlistKeywords = [...s.discoveryWatchlistKeywords];
    excludeKeywords = [...s.discoveryExcludeKeywords];
    locations = [...s.discoveryLocations];
    hideNoSponsorship = s.discoveryHideNoSponsorship;
    scanHours = s.discoveryScanHours;
    listUrls = [...s.discoveryListUrls];
  }
  untrack(() => fill(settings));

  // --- live match count ---------------------------------------------------------

  let count = $state<number | null>(null);
  let countFailed = $state(false);
  // Bumped on every filter change; a response is applied only if it is still the latest.
  let latest = 0;

  async function countMatches(filters: DiscoveryFilters, request: number) {
    try {
      const n = await getMatchCount(filters);
      if (request !== latest) return;
      count = n;
      countFailed = false;
    } catch {
      if (request !== latest) return;
      countFailed = true;
    }
  }

  $effect(() => {
    const filters: DiscoveryFilters = {
      discoveryTerms: [...terms],
      discoveryCategories: [...categories],
      discoveryIncludeKeywords: [...includeKeywords],
      discoveryWatchlistKeywords: [...watchlistKeywords],
      discoveryExcludeKeywords: [...excludeKeywords],
      discoveryLocations: [...locations],
      discoveryHideNoSponsorship: hideNoSponsorship,
    };
    const request = ++latest;
    const timer = setTimeout(() => void countMatches(filters, request), COUNT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  });

  onDestroy(() => {
    latest += 1; // drop any answer still on its way
  });

  const countText = $derived(
    countFailed
      ? "Couldn't count matching postings."
      : count === null
        ? "Counting matching postings…"
        : `${count} ${count === 1 ? "posting matches" : "postings match"} these filters.`,
  );

  // --- save -----------------------------------------------------------------------

  let saving = $state(false);
  let formError = $state<string | null>(null);
  let fieldErrors = $state<Partial<Record<FieldName, string>>>({});

  const FIELDS: ReadonlySet<string> = new Set<FieldName>([
    "discovery_list_urls",
    "discovery_terms",
    "discovery_categories",
    "discovery_include_keywords",
    "discovery_watchlist_keywords",
    "discovery_exclude_keywords",
    "discovery_locations",
    "discovery_hide_no_sponsorship",
    "discovery_scan_hours",
  ]);

  /** FastAPI 422 items for our fields, keyed by field; anything else is returned as text. */
  function splitValidation(detail: unknown[]): { fields: Partial<Record<FieldName, string>>; other: string[] } {
    const fields: Partial<Record<FieldName, string>> = {};
    const other: string[] = [];
    for (const item of detail) {
      const { loc, msg } = (item ?? {}) as { loc?: unknown; msg?: unknown };
      if (typeof msg !== "string") continue;
      const text = msg.replace(/^Value error, /, "");
      const field = Array.isArray(loc) && loc[0] === "body" ? loc[1] : undefined;
      if (typeof field === "string" && FIELDS.has(field)) fields[field as FieldName] ??= text;
      else other.push(text);
    }
    return { fields, other };
  }

  function payload(): Pick<AppSettings, Field> {
    return {
      discoveryListUrls: [...listUrls],
      discoveryTerms: [...terms],
      discoveryCategories: [...categories],
      discoveryIncludeKeywords: [...includeKeywords],
      discoveryWatchlistKeywords: [...watchlistKeywords],
      discoveryExcludeKeywords: [...excludeKeywords],
      discoveryLocations: [...locations],
      discoveryHideNoSponsorship: hideNoSponsorship,
      discoveryScanHours: scanHours as number,
    };
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    formError = null;
    fieldErrors = {};
    try {
      const saved = await updateSettings(payload());
      fill(saved);
      showToast("Job discovery settings saved.", "info");
      onsaved?.(saved);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail)) {
        const { fields, other } = splitValidation(err.detail);
        fieldErrors = fields;
        const lead = Object.keys(fields).length ? ["Some settings weren't saved. Fix the fields marked below."] : [];
        formError = [...lead, ...other].join(" ") || err.message;
      } else {
        formError = err instanceof ApiError
          ? `Couldn't save job discovery settings: ${err.message}`
          : "Couldn't save job discovery settings.";
      }
    } finally {
      saving = false;
    }
  }

  const httpsOnly = (value: string) =>
    /^https:\/\/[^/\s]+/i.test(value) ? null : "List URLs must start with https://.";
</script>

<section class="discovery" aria-labelledby="discovery-heading">
  <h2 id="discovery-heading">Job discovery</h2>
  <p class="muted">
    These filters decide which postings reach your Discover Inbox. Changes apply to postings already found, too.
  </p>
  <p class="count" role="status">{countText}</p>

  <form aria-label="Job discovery settings" onsubmit={save}>
    <ChipInput
      label="Terms"
      hint="Community-list postings must be for one of these terms."
      placeholder="e.g. Summer 2027"
      bind:items={terms}
      error={fieldErrors.discovery_terms}
    />
    <ChipInput
      label="Categories"
      hint="Community-list categories to show. Leave empty for every category."
      suggestions={CATEGORY_SUGGESTIONS}
      bind:items={categories}
      error={fieldErrors.discovery_categories}
    />
    <ChipInput
      label="Include keywords"
      hint="Titles must contain one of these words. Leave empty for any title."
      bind:items={includeKeywords}
      error={fieldErrors.discovery_include_keywords}
    />
    <ChipInput
      label="Watchlist keywords"
      hint="Jobs from watched companies count only when the title contains one of these."
      bind:items={watchlistKeywords}
      error={fieldErrors.discovery_watchlist_keywords}
    />
    <ChipInput
      label="Exclude keywords"
      hint="Hide titles containing any of these."
      bind:items={excludeKeywords}
      error={fieldErrors.discovery_exclude_keywords}
    />
    <ChipInput
      label="Locations"
      hint={'Show postings in any of these places ("Remote" works). Leave empty for anywhere.'}
      bind:items={locations}
      error={fieldErrors.discovery_locations}
    />

    <div class="field">
      <label class="check">
        <input
          type="checkbox"
          aria-invalid={fieldErrors.discovery_hide_no_sponsorship ? "true" : undefined}
          bind:checked={hideNoSponsorship}
        />
        Hide postings that don't offer sponsorship
      </label>
      <p class="muted small">Only catches postings a list marks explicitly; most don't say.</p>
      {#if fieldErrors.discovery_hide_no_sponsorship}
        <p class="field-error">{fieldErrors.discovery_hide_no_sponsorship}</p>
      {/if}
    </div>

    <div class="field">
      <label>
        Scan every (hours)
        <input
          type="number"
          required
          min="1"
          max="48"
          aria-invalid={fieldErrors.discovery_scan_hours ? "true" : undefined}
          aria-describedby={fieldErrors.discovery_scan_hours ? "discovery-scan-hours-error" : undefined}
          bind:value={scanHours}
        />
      </label>
      {#if fieldErrors.discovery_scan_hours}
        <p class="field-error" id="discovery-scan-hours-error">{fieldErrors.discovery_scan_hours}</p>
      {/if}
    </div>

    <details open={fieldErrors.discovery_list_urls ? true : undefined}>
      <summary>Advanced: community list URLs</summary>
      <ChipInput
        label="List URLs"
        hint="The GitHub listings.json files scanned for internships (https only)."
        maxItems={MAX_URLS}
        maxLength={MAX_URL_LENGTH}
        validate={httpsOnly}
        bind:items={listUrls}
        error={fieldErrors.discovery_list_urls}
      />
    </details>

    {#if formError}
      <p class="error" role="alert">{formError}</p>
    {/if}
    <button type="submit" disabled={saving}>Save job discovery settings</button>
  </form>
</section>

<style>
  .discovery { max-width: 40rem; margin-bottom: 1.5rem; }
  .muted { color: #666; }
  .small { font-size: 0.85rem; margin: 0; }
  .count { font-weight: 600; }
  form { display: flex; flex-direction: column; gap: 1rem; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  .check { display: flex; align-items: center; gap: 0.4rem; }
  input[type="number"] { width: 5rem; margin-left: 0.5rem; }
  details summary { cursor: pointer; margin-bottom: 0.5rem; }
  .field-error { margin: 0; color: #b3261e; font-size: 0.85rem; }
  .error { color: #b3261e; margin: 0; overflow-wrap: anywhere; }
  button[type="submit"] { align-self: flex-start; }
</style>
