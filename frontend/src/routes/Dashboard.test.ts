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
vi.mock("../lib/api/discovery", () => ({
  listPostings: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));
vi.mock("../lib/api/interviews", () => ({ listRounds: vi.fn().mockResolvedValue([]) }));
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
  it("loads applications on mount and renders all seven widgets", () => {
    const { container } = render(Dashboard);
    expect(load).toHaveBeenCalledTimes(1);
    for (const id of ["activity", "reminders", "buckets", "snapshot", "needs-attention", "new-postings", "interviews"]) {
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

  it("shows widgets added after an older layout was saved, including Needs attention and New postings", () => {
    localStorage.setItem(
      LAYOUT_STORAGE_KEY,
      JSON.stringify([{ id: "activity", x: 0, y: 0, w: 6, h: 4, settings: {} }]),
    );
    const { container } = render(Dashboard);
    expect(container.querySelectorAll("[data-widget]")).toHaveLength(7);
    expect(container.querySelector('[data-widget="needs-attention"]')).not.toBeNull();
    expect(container.querySelector('[data-widget="new-postings"]')).not.toBeNull();
  });

  it("adds New postings to a full pre-Phase-2 layout and keeps the saved positions", async () => {
    const old = [
      { id: "activity", x: 6, y: 0, w: 6, h: 4, settings: {} },
      { id: "reminders", x: 0, y: 0, w: 6, h: 4, settings: { withinDays: 7 } },
      { id: "buckets", x: 0, y: 4, w: 6, h: 4, settings: {} },
      { id: "snapshot", x: 6, y: 4, w: 6, h: 4, settings: {} },
      { id: "needs-attention", x: 0, y: 8, w: 12, h: 4, settings: {} },
    ];
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(old));
    const { container } = render(Dashboard);
    const card = container.querySelector('[data-widget="new-postings"]');
    expect(card?.querySelector("h2")?.textContent).toBe("New postings");
    expect(await screen.findByText(/No new matches/)).toBeInTheDocument();
    expect((screen.getByLabelText("Days ahead") as HTMLSelectElement).value).toBe("7");
  });

  it("adds Upcoming interviews to a saved pre-Phase-4 layout, keeping saved positions and settings", async () => {
    const old = [
      { id: "activity", x: 6, y: 0, w: 6, h: 4, settings: {} },
      { id: "reminders", x: 0, y: 0, w: 6, h: 4, settings: { withinDays: 30 } },
      { id: "buckets", x: 0, y: 4, w: 6, h: 4, settings: {} },
      { id: "snapshot", x: 6, y: 4, w: 6, h: 4, settings: {} },
      { id: "needs-attention", x: 0, y: 8, w: 12, h: 4, settings: {} },
      { id: "new-postings", x: 0, y: 12, w: 6, h: 4, settings: {} },
    ];
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(old));
    const { container } = render(Dashboard);
    const card = container.querySelector('[data-widget="interviews"]');
    expect(card?.querySelector("h2")?.textContent).toBe("Upcoming interviews");
    expect(await screen.findByText(/No interviews in the next 14 days/)).toBeInTheDocument();
    expect((screen.getByLabelText("Days ahead") as HTMLSelectElement).value).toBe("30");
  });

  it("toasts when loading applications fails", async () => {
    load.mockRejectedValue(new Error("down"));
    render(Dashboard);
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toContain("Couldn't load applications."));
  });
});
