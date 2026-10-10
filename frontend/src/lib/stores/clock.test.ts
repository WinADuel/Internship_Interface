import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TICK_MS, clock } from "./clock";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 9, 9, 0));
});
afterEach(() => vi.useRealTimers());

describe("clock", () => {
  it("ticks once a minute on one shared interval and stops with the last subscriber", () => {
    const seen: Date[] = [];
    const stopA = clock.subscribe((d) => seen.push(d));
    const stopB = clock.subscribe(() => {});
    expect(vi.getTimerCount()).toBe(1);
    expect(seen.at(-1)).toEqual(new Date(2026, 9, 9, 9, 0));
    vi.advanceTimersByTime(TICK_MS);
    expect(seen.at(-1)).toEqual(new Date(2026, 9, 9, 9, 1));
    stopA();
    expect(vi.getTimerCount()).toBe(1);
    stopB();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("starts from the current time when first shown again", () => {
    vi.setSystemTime(new Date(2026, 9, 10, 8, 30));
    expect(get(clock)).toEqual(new Date(2026, 9, 10, 8, 30));
    expect(vi.getTimerCount()).toBe(0);
  });
});
