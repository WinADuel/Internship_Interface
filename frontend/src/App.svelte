<script lang="ts">
  import Router, { push, router } from "svelte-spa-router";
  import NavSidebar from "./lib/components/NavSidebar.svelte";
  import Toast from "./lib/components/Toast.svelte";
  import { session } from "./lib/stores/session";
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

  $effect(() => {
    if (!$session.loggedIn && router.location !== "/login") push("/login");
  });
</script>

<div class="layout">
  <NavSidebar />
  <main><Router {routes} /></main>
</div>
<Toast />

<style>
  .layout { display: flex; min-height: 100vh; }
  main { flex: 1; padding: 1rem; }
</style>
