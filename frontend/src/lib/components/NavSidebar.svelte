<script lang="ts">
  import { push } from "svelte-spa-router";
  import { discoveryStatus, refreshDiscoveryStatus } from "../stores/discovery";
  import { logout, session } from "../stores/session";
  import { showToast } from "../stores/toast";

  const inboxCount = $derived($discoveryStatus?.inboxCount ?? 0);

  // Load the Inbox count once signed in (and again after a fresh sign-in).
  $effect(() => {
    if ($session.loggedIn) void refreshDiscoveryStatus();
  });

  async function onLogout() {
    try {
      await logout();
    } catch (err) {
      showToast(`Couldn't log out: ${err instanceof Error ? err.message : "unknown error"}`);
      return;
    }
    await push("/login");
  }
</script>

<nav class="sidebar" aria-label="Main">
  <a href="#/">Dashboard</a>
  <a href="#/applications">Applications</a>
  <a href="#/discover" aria-label={inboxCount > 0 ? `Discover (${inboxCount} new)` : undefined}>
    Discover{#if inboxCount > 0}<span class="badge" aria-hidden="true">{inboxCount}</span>{/if}
  </a>
  <a href="#/contacts">Contacts</a>
  <a href="#/research-queue">Research Queue</a>
  <a href="#/essays">Essays</a>
  <span class="disabled" aria-disabled="true">Interview Prep <small>Coming soon</small></span>
  <span class="disabled" aria-disabled="true">Email Sync <small>Coming soon</small></span>
  <a href="#/settings" class="settings">Settings</a>
  {#if $session.loggedIn}
    <button type="button" class="logout" onclick={onLogout}>Log out</button>
  {/if}
</nav>

<style>
  .sidebar { display: flex; flex-direction: column; gap: 0.5rem; padding: 1rem; min-width: 12rem; border-right: 1px solid #ddd; }
  .disabled { color: #999; cursor: not-allowed; }
  .badge { display: inline-block; margin-left: 0.4rem; padding: 0 0.45rem; border-radius: 999px; font-size: 0.75rem; background: #1a5fb4; color: #fff; }
  small { display: block; font-size: 0.7rem; }
  /* Settings and Log out sit together at the bottom. */
  .settings { margin-top: auto; }
  .logout { align-self: flex-start; }

  /* Phones: collapse into a top bar that wraps onto a second row, so every link (Settings and
     Log out included) is on screen without a sideways scroll. The Coming soon placeholders go. */
  @media (max-width: 700px) {
    .sidebar { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 0.5rem 1rem; min-width: 0; padding: 0.5rem 0.75rem; border-right: 0; border-bottom: 1px solid #ddd; white-space: nowrap; }
    .sidebar > * { flex: 0 0 auto; }
    .disabled { display: none; }
    .settings { margin: 0 0 0 auto; }
  }
</style>
