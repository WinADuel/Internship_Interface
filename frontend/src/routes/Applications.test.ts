import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApplication } from "../lib/testing/fixtures";

const { store, load } = vi.hoisted(() => ({ store: { current: null as any }, load: vi.fn() }));
vi.mock("../lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  store.current = writable([]);
  return { applications: store.current, loadApplications: load, moveApplicationStatus: vi.fn() };
});
vi.mock("../lib/api/applications", () => ({ getStatusHistory: vi.fn().mockResolvedValue([]) }));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import Applications from "./Applications.svelte";

describe("Applications route", () => {
  beforeEach(() => {
    load.mockReset().mockResolvedValue(undefined);
    store.current.set([fakeApplication({ id: 3, company: "Initech", roleTitle: "Intern" })]);
  });

  it("loads applications on mount", () => {
    render(Applications);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("opens the detail panel on card click and closes on Escape", async () => {
    render(Applications);
    expect(screen.queryByLabelText("Application details")).toBeNull();
    await fireEvent.click(screen.getByText("Initech"));
    expect(screen.getByLabelText("Application details")).toBeTruthy();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByLabelText("Application details")).toBeNull();
  });
});
