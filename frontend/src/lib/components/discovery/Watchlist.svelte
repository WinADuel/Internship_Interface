<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../api/client";
  import { addWatchCompany, listWatchlist, removeWatchCompany } from "../../api/discovery";
  import { sourceLabel, timeAgo } from "../../discovery/format";
  import { showToast } from "../../stores/toast";
  import type { WatchCompany } from "../../types/discovery";

  let companies = $state<WatchCompany[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  let careersUrl = $state("");
  let name = $state("");
  let adding = $state(false);
  let addError = $state<string | null>(null);
  let removing = $state<number | null>(null);

  const message = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

  // Same order as the backend list: by name, ignoring case.
  const byName = (a: WatchCompany, b: WatchCompany) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.id - b.id;

  async function load() {
    loading = true;
    loadError = null;
    try {
      companies = await listWatchlist();
    } catch (err) {
      loadError = message(err, "something went wrong");
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
  });

  async function add(event: SubmitEvent) {
    event.preventDefault();
    adding = true;
    addError = null;
    try {
      const company = await addWatchCompany({ careersUrl: careersUrl.trim(), name: name.trim() || null });
      companies = [...companies.filter((c) => c.id !== company.id), company].sort(byName);
      careersUrl = "";
      name = "";
      showToast(`Watching ${company.name}. Its internships arrive with the next scan.`, "info");
    } catch (err) {
      // 422 carries the service's readable reason (e.g. a custom careers site).
      addError = message(err, "Couldn't add that company.");
    } finally {
      adding = false;
    }
  }

  async function remove(company: WatchCompany) {
    if (!window.confirm(`Stop watching ${company.name}? Postings already found stay.`)) return;
    removing = company.id;
    try {
      await removeWatchCompany(company.id);
      companies = companies.filter((c) => c.id !== company.id);
    } catch (err) {
      showToast(err instanceof ApiError ? `Couldn't remove ${company.name}: ${err.message}` : `Couldn't remove ${company.name}.`);
    } finally {
      removing = null;
    }
  }

  const matches = (n: number) => `${n} open ${n === 1 ? "match" : "matches"}`;
</script>

<section class="watchlist" aria-labelledby="watchlist-heading">
  <h2 id="watchlist-heading">Company watchlist</h2>
  <p class="muted">
    Paste a company's careers page on Greenhouse, Lever, Ashby or Workday. Each scan checks its board for internships.
  </p>

  <form class="add" onsubmit={add}>
    <label class="url">
      Careers page URL
      <input type="url" required maxlength="2000" placeholder="https://boards.greenhouse.io/…" bind:value={careersUrl} />
    </label>
    <label>
      Name (optional)
      <input maxlength="200" bind:value={name} />
    </label>
    <button type="submit" disabled={adding}>Add</button>
  </form>
  {#if addError}
    <p class="error" role="alert">{addError}</p>
  {/if}
  <p class="muted note">
    Google, Microsoft, Apple, Meta and Amazon use their own sites; their internships come in through the community lists.
  </p>

  {#if loadError}
    <p class="error" role="alert">
      Couldn't load the watchlist: {loadError}
      <button type="button" onclick={load}>Retry</button>
    </p>
  {:else if loading}
    <p class="muted">Loading…</p>
  {:else if companies.length === 0}
    <p class="muted">No companies yet. Add one above to watch its job board.</p>
  {:else}
    <ul class="companies">
      {#each companies as company (company.id)}
        <li>
          <div class="head">
            <h3>{company.name}</h3>
            <span class="system">{sourceLabel(company.ats)}</span>
          </div>
          <div class="meta">
            <span>{company.lastCheckedAt ? `Checked ${timeAgo(company.lastCheckedAt)}` : "Not checked yet"}</span>
            <span>{matches(company.openMatches)}</span>
          </div>
          {#if company.lastError}
            <p class="row-error">Last check failed: {company.lastError}</p>
          {/if}
          <button
            type="button"
            aria-label={`Remove ${company.name} from the watchlist`}
            disabled={removing === company.id}
            onclick={() => remove(company)}
          >
            Remove
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .watchlist { max-width: 40rem; }
  h2 { font-size: 1rem; margin: 0 0 0.3rem; }
  .add { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.5rem; }
  .add label { display: flex; flex-direction: column; gap: 0.15rem; }
  .add .url { flex: 1 1 18rem; }
  input { font: inherit; min-width: 0; }
  .muted { color: #555; font-size: 0.9rem; }
  .note { margin: 0.5rem 0 0.75rem; }
  .error { color: #b3261e; margin: 0.4rem 0 0; overflow-wrap: anywhere; }
  .companies { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .companies li { border: 1px solid #ddd; border-radius: 6px; padding: 0.5rem 0.7rem; display: flex; flex-direction: column; align-items: flex-start; gap: 0.25rem; }
  .head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem; }
  h3 { font-size: 1rem; margin: 0; overflow-wrap: anywhere; }
  .system { font-size: 0.75rem; padding: 0.05rem 0.4rem; border-radius: 999px; background: #eef2f7; color: #333; }
  .meta { display: flex; flex-wrap: wrap; gap: 0.75rem; color: #555; font-size: 0.85rem; }
  .row-error { margin: 0; color: #8c1d18; font-size: 0.85rem; overflow-wrap: anywhere; }
</style>
