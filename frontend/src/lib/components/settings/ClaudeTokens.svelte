<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import { ApiError } from "../../api/client";
  import { createClaudeToken, listClaudeTokens, revokeClaudeToken } from "../../api/settings";
  import { formatDateTime } from "../../format";
  import { showToast } from "../../stores/toast";
  import type { ClaudeTokenInfo } from "../../types/contact";

  let tokens = $state<ClaudeTokenInfo[]>([]);
  // The plaintext lives only here, only until dismissed or the component goes away.
  let plaintext = $state<string | null>(null);
  let creating = $state(false);
  let alive = true;
  let tokenInput = $state<HTMLInputElement | null>(null);
  let createButton = $state<HTMLButtonElement | null>(null);

  const message = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

  // Keep only the listed fields, so a token value can never end up in the list even if the API sent one.
  function strip(t: ClaudeTokenInfo): ClaudeTokenInfo {
    return { id: t.id, tokenPrefix: t.tokenPrefix, createdAt: t.createdAt, lastUsedAt: t.lastUsedAt, revokedAt: t.revokedAt };
  }

  async function load() {
    try {
      tokens = (await listClaudeTokens()).map(strip);
    } catch (err) {
      showToast(message(err, "Couldn't load Claude tokens."));
    }
  }

  const clearPlaintext = () => (plaintext = null);

  onMount(() => {
    void load();
    // Leaving the app entirely (another URL, Connect Google) can keep this page in
    // the back/forward cache, so drop the secret before the page is hidden too.
    window.addEventListener("pagehide", clearPlaintext);
    return () => window.removeEventListener("pagehide", clearPlaintext);
  });
  onDestroy(() => {
    alive = false;
    clearPlaintext();
  });

  async function create() {
    creating = true;
    try {
      const created = await createClaudeToken();
      if (!alive) {
        // Navigated away before the token arrived: nobody can copy it, so don't leave it active.
        void revokeClaudeToken(created.id).catch(() => undefined);
        return;
      }
      plaintext = created.token;
      tokens = [strip(created), ...tokens];
      await tick();
      tokenInput?.focus();
      tokenInput?.select();
    } catch (err) {
      showToast(message(err, "Couldn't create a token."));
    } finally {
      creating = false;
    }
  }

  async function copy() {
    if (!plaintext) return;
    try {
      await navigator.clipboard.writeText(plaintext);
      showToast("Token copied.", "info");
    } catch {
      showToast("Couldn't copy. Select the field and copy it by hand.");
    }
  }

  function dismiss() {
    clearPlaintext();
    createButton?.focus();
  }

  async function revoke(token: ClaudeTokenInfo) {
    if (!window.confirm(`Revoke ${token.tokenPrefix}…? The Claude job using it will stop working.`)) return;
    try {
      const updated = strip(await revokeClaudeToken(token.id));
      tokens = tokens.map((t) => (t.id === updated.id ? updated : t));
    } catch (err) {
      showToast(message(err, "Couldn't revoke the token."));
    }
  }
</script>

<section aria-labelledby="claude-tokens-heading">
  <h2 id="claude-tokens-heading">Claude tokens</h2>
  <p class="muted">The daily Claude job uses one of these to read the research queue and post contacts.</p>

  {#if plaintext}
    <div class="new-token">
      <label>
        New token
        <input
          type="text"
          readonly
          autocomplete="off"
          spellcheck="false"
          value={plaintext}
          bind:this={tokenInput}
          onfocus={(e) => e.currentTarget.select()}
        />
      </label>
      <p class="warning">Copy this now — it won't be shown again.</p>
      <button type="button" onclick={copy}>Copy</button>
      <button type="button" onclick={dismiss}>Done</button>
    </div>
  {/if}

  <button type="button" bind:this={createButton} onclick={create} disabled={creating}>Create token</button>

  {#if tokens.length === 0}
    <p class="muted">No tokens yet.</p>
  {:else}
    <table>
      <thead>
        <tr><th>Token</th><th>Created</th><th>Last used</th><th>State</th><th><span class="visually-hidden">Actions</span></th></tr>
      </thead>
      <tbody>
        {#each tokens as token (token.id)}
          <tr>
            <td><code>{token.tokenPrefix}…</code></td>
            <td>{formatDateTime(token.createdAt)}</td>
            <td>{token.lastUsedAt ? formatDateTime(token.lastUsedAt) : "Never used"}</td>
            <td>{token.revokedAt ? "Revoked" : "Active"}</td>
            <td>
              {#if !token.revokedAt}
                <button type="button" aria-label={`Revoke ${token.tokenPrefix}…`} onclick={() => revoke(token)}>
                  Revoke
                </button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .muted { color: #666; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .new-token { border: 1px solid #c90; background: #fff8e1; padding: 0.75rem; margin-bottom: 0.75rem; }
  .new-token input { width: 100%; font-family: monospace; box-sizing: border-box; }
  .warning { font-weight: 600; }
  table { border-collapse: collapse; margin-top: 0.75rem; }
  th, td { text-align: left; padding: 0.25rem 0.75rem 0.25rem 0; }
</style>
