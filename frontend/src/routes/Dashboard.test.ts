import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { load } = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock("../lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  return { applications: writable([]), loadApplications: load, moveApplicationStatus: vi.fn() };
});
vi.mock("gridstack", () => ({
  GridStack: { init: vi.fn(() => ({ on: vi.fn(), save: vi.fn(() => []), destroy: vi.fn() })) },
}));
vi.mock("gridstack/dist/gridstack.min.css", () => ({}));
vi.mock("../lib/api/contacts", () => ({
  getNeedsAttention: vi.fn().mockResolvedValue([]),
  getContactActivity: vi.fn().mockResolvedValue([]),
}));
vi.mock("../lib/api/applications", async (orig) => ({
  ...(await orig<typeof import("../lib/api/applications")>()),
  getRecentActivity: vi.fn().mockResolvedValue([]),
}));

import { get } from "svelte/store";
import Dashboard from "./Dashboard.svelte";
import { LAYOUT_STORAGE_KEY } from "../lib/dashboard/layout";
import { toasts } from "../lib/stores/toast";

beforeEach(() => {
  load.mockReset().mockResolvedValue(undefined);
  localStorage.clear();
  toasts.set([]);
});

describe("Dashboard route", () => {
  it("loads applications on mount and renders all five widgets", () => {
    const { container } = render(Dashboard);
    expect(load).toHaveBeenCalledTimes(1);
    for (const id of ["activity", "reminders", "buckets", "snapshot", "needs-attention"]) {
      expect(container.querySelector(`[data-widget="${id}"]`)).not.toBeNull();
    }
  });

  it("persists a settings change under the layout key and restores it on remount", async () => {
    const first = render(Dashboard);
    await fireEvent.change(screen.getByLabelText("Days ahead"), { target: { value: "30" } });
    const saved = JSON.parse(localStorage.getItem(LAYOUT_STORAGE_KEY)!);
    expect(saved.find((e: any) => e.id === "reminders").settings).toEqual({ withinDays: 30 });
    first.unmount();
    render(Dashboard);
    expect((screen.getByLabelText("Days ahead") as HTMLSelectElement).value).toBe("30");
  });

  it("shows widgets added after an older layout was saved, including Needs attention", () => {
    localStorage.setItem(
      LAYOUT_STORAGE_KEY,
      JSON.stringify([{ id: "activity", x: 0, y: 0, w: 6, h: 4, settings: {} }]),
    );
    const { container } = render(Dashboard);
    expect(container.querySelectorAll("[data-widget]")).toHaveLength(5);
    expect(container.querySelector('[data-widget="needs-attention"]')).not.toBeNull();
  });

  it("toasts when loading applications fails", async () => {
    load.mockRejectedValue(new Error("down"));
    render(Dashboard);
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toContain("Couldn't load applications."));
  });
});
