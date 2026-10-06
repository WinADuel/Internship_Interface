<script lang="ts">
  import { onMount } from "svelte";
  import Router, { push, router } from "svelte-spa-router";
  import NavSidebar from "./lib/components/NavSidebar.svelte";
  import Toast from "./lib/components/Toast.svelte";
  import { session, checkSession } from "./lib/stores/session";
  import Dashboard from "./routes/Dashboard.svelte";
  import Login from "./routes/Login.svelte";
  import Applications from "./routes/Applications.svelte";
  import Essays from "./routes/Essays.svelte";

  const routes = {
    "/": Dashboard,
    "/login": Login,
    "/applications": Applications,
    "/essays": Essays,
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
  .layout { display: flex; min-height: 100vh; }
  main { flex: 1; padding: 1rem; }
</style>
