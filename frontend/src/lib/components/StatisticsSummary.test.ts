import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { load } = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock("$lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  const { fakeApplication } = await import("$lib/testing/fixtures");
  return {
    applications: writable([
      fakeApplication({ id: 1, status: "applied" }),
      fakeApplication({ id: 2, status: "interview" }),
      fakeApplication({ id: 3, status: "wishlist" }),
    ]),
    loadApplications: load,
  };
});
vi.mock("$lib/api/interviews", () => ({ listRounds: vi.fn().mockResolvedValue([]) }));
vi.mock("$lib/api/email", () => ({ getEmailStatus: vi.fn() }));

import { getEmailStatus } from "$lib/api/email";
import { emailStatus } from "$lib/stores/email";
import { fakeEmailStatus, fakeGmailAccount } from "$lib/testing/fixtures";
import Statistics from "./StatisticsSummary.svelte";

beforeEach(() => {
  localStorage.clear();
  emailStatus.set(null);
  load.mockReset().mockResolvedValue(undefined);
  vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 3, accounts: [fakeGmailAccount(), fakeGmailAccount({ id: 2 })] }));
});

describe("Statistics summary", () => {
  it("shows the four totals and the kanban snapshot", async () => {
    const { container } = render(Statistics);
    const tile = (id: string) => container.querySelector(`[data-stat="${id}"] .value`)?.textContent;
    expect(tile("sent")).toBe("2");
    expect(tile("response-rate")).toBe("50%");
    expect(await screen.findByText(/From 2 inboxes/)).toBeInTheDocument();
    expect(tile("replies")).toBe("3");
    expect(tile("interviews")).toBe("0");
    expect(container.querySelector('[data-widget="snapshot"]')).not.toBeNull();
    expect(screen.getByLabelText("Columns shown")).toBeInTheDocument();
  });
});
