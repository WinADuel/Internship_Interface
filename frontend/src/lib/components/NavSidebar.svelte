<script lang="ts">
  import { push } from "svelte-spa-router";
  import { logout, session } from "../stores/session";
  import { showToast } from "../stores/toast";

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
  <a href="#/contacts">Contacts</a>
  <a href="#/research-queue">Research Queue</a>
  <a href="#/essays">Essays</a>
  <span class="disabled" aria-disabled="true">Job Discovery <small>Coming soon</small></span>
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
  small { display: block; font-size: 0.7rem; }
  /* Settings and Log out sit together at the bottom. */
  .settings { margin-top: auto; }
  .logout { align-self: flex-start; }

  /* Phones: collapse into a top bar that scrolls sideways instead of eating the screen width. */
  @media (max-width: 700px) {
    .sidebar { flex-direction: row; align-items: center; gap: 1rem; min-width: 0; padding: 0.5rem 0.75rem; border-right: 0; border-bottom: 1px solid #ddd; overflow-x: auto; white-space: nowrap; }
    .sidebar > * { flex: 0 0 auto; }
    small { display: none; }
    .settings { margin: 0 0 0 auto; }
  }
</style>
