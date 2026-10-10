import { readable } from "svelte/store";

export const TICK_MS = 60_000;

/**
 * The current time, refreshed once a minute while anything shows it, so a
 * countdown ("in 5 minutes") on a page left open stays current. One interval
 * serves every subscriber; it stops when the last one goes away.
 */
export const clock = readable(new Date(), (set) => {
  set(new Date());
  const timer = setInterval(() => set(new Date()), TICK_MS);
  return () => clearInterval(timer);
});
