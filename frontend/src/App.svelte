<script lang="ts">
  import { onMount } from "svelte";
  import Router, { push, router } from "svelte-spa-router";
  import NavSidebar from "./lib/components/NavSidebar.svelte";
  import Toast from "./lib/components/Toast.svelte";
  import { session, checkSession } from "./lib/stores/session";
  import Dashboard from "./routes/Dashboard.svelte";
  import Login from "./routes/Login.svelte";
  import Applications from "./routes/Applications.svelte";
  import Discover from "./routes/Discover.svelte";
  import Essays from "./routes/Essays.svelte";
  import Contacts from "./routes/Contacts.svelte";
  import ResearchQueue from "./routes/ResearchQueue.svelte";
  import Settings from "./routes/Settings.svelte";
  import Interviews from "./routes/Interviews.svelte";

  const routes = {
    "/": Dashboard,
    "/login": Login,
    "/applications": Applications,
    "/discover": Discover,
    "/essays": Essays,
    "/contacts": Contacts,
    "/research-queue": ResearchQueue,
    "/interviews": Interviews,
    "/settings": Settings,
  };

  onMount(() => {
    void checkSession();
  });

  $effect(() => {
    if (!$session.checked) return;
    if (!$session.loggedIn && router.location !== "/login") push("/login");
    else if ($session.loggedIn && router.location === "/login") push("/");
  });
</script>

{#if !$session.checked}
  <p class="loading">Loading…</p>
{:else}
  <div class="layout">
    <NavSidebar />
    <main><Router {routes} /></main>
  </div>
{/if}
<Toast />

<style>
  :global(body) { margin: 0; }
  .layout { display: flex; min-height: 100vh; }
  main { flex: 1; min-width: 0; padding: 1rem; }

  /* Phones: the navigation becomes a top bar above the content, which then uses the full width. */
  @media (max-width: 700px) {
    .layout { flex-direction: column; }
    main { flex: 1 1 auto; width: 100%; box-sizing: border-box; padding: 0.75rem; }
  }
</style>
