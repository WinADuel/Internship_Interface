/** A reactive stand-in for svelte-spa-router's `router`, so tests can change the querystring of a mounted page. */
export const routerState = $state<{ querystring: string | undefined }>({ querystring: "" });
