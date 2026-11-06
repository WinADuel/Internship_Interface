<script lang="ts">
  import { onMount, type Component } from "svelte";
  import { push } from "svelte-spa-router";
  import BarChart3 from "@lucide/svelte/icons/chart-column";
  import Briefcase from "@lucide/svelte/icons/briefcase";
  import FileText from "@lucide/svelte/icons/file-text";
  import LayoutDashboard from "@lucide/svelte/icons/layout-dashboard";
  import ListTodo from "@lucide/svelte/icons/list-todo";
  import LogOut from "@lucide/svelte/icons/log-out";
  import Mail from "@lucide/svelte/icons/mail";
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import Search from "@lucide/svelte/icons/search";
  import Settings from "@lucide/svelte/icons/settings";
  import Users from "@lucide/svelte/icons/users";
  import { discoveryStatus, refreshDiscoveryStatus } from "../stores/discovery";
  import { emailStatus, refreshEmailStatus } from "../stores/email";
  import { logout, session } from "../stores/session";
  import { showToast } from "../stores/toast";

  const inboxCount = $derived($discoveryStatus?.inboxCount ?? 0);
  const emailCount = $derived($emailStatus?.pendingCount ?? 0);

  // Load the badge counts once signed in (and again after a fresh sign-in).
  $effect(() => {
    if (!$session.loggedIn) return;
    void refreshDiscoveryStatus();
    void refreshEmailStatus();
  });

  // The current page, read from the hash so the matching link can be highlighted.
  let path = $state(currentPath());
  function currentPath(): string {
    return (typeof location === "undefined" ? "" : location.hash.replace(/^#/, "")) || "/";
  }
  onMount(() => {
    const onHash = () => (path = currentPath());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  });
  function isActive(href: string): boolean {
    const target = href.replace(/^#/, "");
    return target === "/" ? path === "/" : path === target || path.startsWith(`${target}/`);
  }

  interface NavItem {
    href: string;
    label: string;
    icon: Component;
    count?: () => number;
    countLabel?: (n: number) => string;
  }

  const items: NavItem[] = [
    { href: "#/", label: "Dashboard", icon: LayoutDashboard },
    { href: "#/statistics", label: "Statistics", icon: BarChart3 },
    { href: "#/applications", label: "Applications", icon: Briefcase },
    { href: "#/discover", label: "Discover", icon: Search, count: () => inboxCount, countLabel: (n) => `Discover (${n} new)` },
    { href: "#/contacts", label: "Contacts", icon: Users },
    { href: "#/research-queue", label: "Research Queue", icon: ListTodo },
    { href: "#/essays", label: "Essays", icon: FileText },
    { href: "#/interviews", label: "Interview Prep", icon: MessagesSquare },
    { href: "#/email", label: "Email updates", icon: Mail, count: () => emailCount, countLabel: (n) => `Email updates (${n} to review)` },
  ];

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

<aside class="sidebar">
  <div class="brand" aria-hidden="true">
    <span class="logo">IH</span>
    <span class="name">InternHelper</span>
  </div>

  <nav aria-label="Main">
    {#each items as item (item.href)}
      {@const n = item.count?.() ?? 0}
      <a
        href={item.href}
        class:active={isActive(item.href)}
        aria-current={isActive(item.href) ? "page" : undefined}
        aria-label={n > 0 && item.countLabel ? item.countLabel(n) : undefined}
      >
        <item.icon class="icon" aria-hidden="true" />
        <span class="label">{item.label}</span>{#if n > 0}<span class="badge" aria-hidden="true">{n}</span>{/if}
      </a>
    {/each}
  </nav>

  <!-- Settings and Log out stay pinned to the bottom of the sidebar, always on screen. -->
  <div class="bottom">
    <a href="#/settings" class:active={isActive("#/settings")} aria-current={isActive("#/settings") ? "page" : undefined}>
      <Settings class="icon" aria-hidden="true" />
      <span class="label">Settings</span>
    </a>
    {#if $session.loggedIn}
      <button type="button" class="logout" onclick={onLogout}>
        <LogOut class="icon" aria-hidden="true" />
        <span class="label">Log out</span>
      </button>
    {/if}
  </div>
</aside>

<style>
  .sidebar {
    position: sticky;
    top: 0;
    height: 100vh;
    height: 100dvh;
    flex: 0 0 15rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding: 0.75rem;
    background: var(--sidebar);
    color: var(--sidebar-foreground);
    border-right: 1px solid var(--sidebar-border);
    z-index: 20;
  }
  .brand { display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0.5rem; font-weight: 600; }
  .logo {
    display: grid; place-items: center; width: 1.85rem; height: 1.85rem; border-radius: 0.45rem;
    background: var(--sidebar-primary); color: var(--sidebar-primary-foreground); font-size: 0.75rem; font-weight: 700;
  }
  nav { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
  .bottom { display: flex; flex-direction: column; gap: 2px; padding-top: 0.6rem; border-top: 1px solid var(--sidebar-border); }

  a, .logout {
    display: flex; align-items: center; gap: 0.6rem; width: 100%;
    padding: 0.45rem 0.55rem; border-radius: var(--radius-md);
    font: inherit; font-size: 0.875rem; font-weight: 450; text-align: left;
    color: var(--sidebar-foreground); text-decoration: none;
    background: transparent; border: 0; box-shadow: none; cursor: pointer;
  }
  a:hover, .logout:hover { background: var(--sidebar-accent); text-decoration: none; }
  a.active { background: var(--sidebar-accent); color: var(--sidebar-accent-foreground); font-weight: 600; }
  .logout { color: var(--muted-foreground); }
  .sidebar :global(.icon) { width: 1rem; height: 1rem; flex: 0 0 1rem; color: var(--muted-foreground); }
  a.active :global(.icon) { color: var(--sidebar-foreground); }
  .badge {
    margin-left: auto; min-width: 1.25rem; padding: 0 0.4rem; border-radius: 0.4rem;
    background: var(--sidebar-primary); color: var(--sidebar-primary-foreground);
    font-size: 0.7rem; font-weight: 600; line-height: 1.25rem; text-align: center; font-variant-numeric: tabular-nums;
  }

  /* Phones: one slim bar that stays at the top while the page scrolls. The page links scroll
     sideways inside it; Settings and Log out sit at its right end, always on screen. */
  @media (max-width: 700px) {
    .sidebar {
      height: auto; flex: 0 0 auto; flex-direction: row; align-items: center; gap: 0.25rem;
      padding: 0.35rem 0.5rem; border-right: 0; border-bottom: 1px solid var(--sidebar-border);
    }
    .brand { display: none; }
    nav { flex: 1 1 auto; min-width: 0; flex-direction: row; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
    nav::-webkit-scrollbar { display: none; }
    .bottom { flex: none; flex-direction: row; padding: 0 0 0 0.35rem; border-top: 0; border-left: 1px solid var(--sidebar-border); }
    a, .logout { width: auto; flex: none; padding: 0.35rem 0.55rem; font-size: 0.8rem; white-space: nowrap; }
    .sidebar :global(.icon) { display: none; }
    .badge { margin-left: 0.3rem; }
  }
</style>
