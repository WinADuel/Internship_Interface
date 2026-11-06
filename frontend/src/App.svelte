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
  import InterviewRound from "./routes/InterviewRound.svelte";
  import Email from "./routes/Email.svelte";
  import Statistics from "./routes/Statistics.svelte";
  import ApplyReview from "./routes/ApplyReview.svelte";

  const routes = {
    "/": Dashboard,
    "/statistics": Statistics,
    "/login": Login,
    "/applications": Applications,
    "/discover": Discover,
    "/essays": Essays,
    "/contacts": Contacts,
    "/research-queue": ResearchQueue,
    "/interviews": Interviews,
    "/interviews/:id": InterviewRound,
    "/email": Email,
    "/apply/:id": ApplyReview,
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
  .loading { padding: 2rem; color: var(--muted-foreground); }
  .layout { display: flex; min-height: 100vh; align-items: flex-start; }
  main { flex: 1; min-width: 0; padding: 1.5rem 2rem 2.5rem; }

  /* Phones: the navigation becomes a top bar above the content, which then uses the full width. */
  @media (max-width: 700px) {
    .layout { flex-direction: column; align-items: stretch; }
    main { flex: 1 1 auto; width: 100%; padding: 0.9rem 0.75rem 1.5rem; }
  }
</style>
