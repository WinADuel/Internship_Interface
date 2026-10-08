/**
 * Moves an element to the end of <body> while it is mounted. Used for
 * slide-over panels rendered from inside a dashboard widget, so they are not
 * inside GridStack's drag handle or a transformed ancestor. Svelte 5 also
 * listens for delegated events on `document`, so handlers keep working.
 */
export function portal(node: HTMLElement): { destroy: () => void } {
  document.body.appendChild(node);
  return { destroy: () => node.remove() };
}
