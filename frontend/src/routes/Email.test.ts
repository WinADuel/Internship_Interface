import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api/email", () => ({
  listSuggestions: vi.fn(),
  acceptSuggestion: vi.fn(),
  dismissSuggestion: vi.fn(),
  getEmailStatus: vi.fn(),
  syncEmailNow: vi.fn(),
}));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../lib/api/client";
import { dismissSuggestion, getEmailStatus, listSuggestions, syncEmailNow } from "../lib/api/email";
import { emailStatus } from "../lib/stores/email";
import { showToast } from "../lib/stores/toast";
import { fakeEmailStatus, fakeSuggestion } from "../lib/testing/fixtures";
import Email from "./Email.svelte";

beforeEach(() => {
  emailStatus.set(null);
  vi.mocked(listSuggestions)
    .mockReset()
    .mockImplementation(async ({ state } = {}) =>
      state === "decided"
        ? [fakeSuggestion({ id: 9, subject: "Offer from Globex", kind: "offer", state: "accepted" })]
        : [fakeSuggestion({ id: 1, subject: "Thank you for applying to Acme" })],
    );
  vi.mocked(getEmailStatus).mockReset().mockResolvedValue(fakeEmailStatus({ pendingCount: 1 }));
  vi.mocked(syncEmailNow).mockReset();
  vi.mocked(dismissSuggestion).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("Email updates page", () => {
  it("lists the pending updates first, with the count on the tab", async () => {
    render(Email);
    expect(screen.getByRole("heading", { name: "Email updates" })).toBeInTheDocument();
    expect(await screen.findByText("Thank you for applying to Acme")).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenCalledWith({ state: "pending" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    await vi.waitFor(() => expect(tabs[0]).toHaveTextContent("Pending (1)"));
    expect(tabs[1]).toHaveTextContent("Recent decisions");
  });

  it("shows recent decisions on the second tab", async () => {
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    await fireEvent.click(screen.getByRole("tab", { name: "Recent decisions" }));
    expect(await screen.findByText("Offer from Globex")).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenLastCalledWith({ state: "decided", limit: 50 });
    expect(screen.queryByText("Thank you for applying to Acme")).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("reloads after a decision", async () => {
    vi.mocked(dismissSuggestion).mockResolvedValue(fakeSuggestion({ state: "dismissed" }));
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    vi.mocked(listSuggestions).mockResolvedValue([]);
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("No email updates to review.")).toBeInTheDocument();
  });

  it("says when Gmail isn't connected, with no Sync now", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ gmailGranted: false, gmailSyncEnabled: false }));
    vi.mocked(listSuggestions).mockResolvedValue([]);
    render(Email);
    const link = await screen.findByRole("link", { name: "Connect Gmail in Settings" });
    expect(link.getAttribute("href")).toBe("#/settings");
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("says when sync is off", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ gmailSyncEnabled: false }));
    render(Email);
    expect(await screen.findByRole("link", { name: "Turn it on in Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("Sync now syncs, announces the outcome and reloads the list", async () => {
    vi.mocked(syncEmailNow).mockResolvedValue({
      ...fakeEmailStatus({ pendingCount: 2, gmailLastSyncAt: "2026-10-09T09:00:00Z" }),
      ok: true,
      fetched: 30,
      suggested: 1,
      autoApplied: 0,
      more: false,
    });
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    await fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByText("Checked 30 emails: 1 update found.")).toBeInTheDocument();
    expect(get(emailStatus)?.pendingCount).toBe(2);
    expect(listSuggestions).toHaveBeenCalledTimes(2);
  });

  it("shows the last sync error and a failed Sync now as a toast", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ gmailLastError: "reconnect Google and allow Gmail" }));
    vi.mocked(syncEmailNow).mockRejectedValue(new ApiError(409, "a Gmail sync is already running"));
    render(Email);
    expect(await screen.findByText("Last sync failed: reconnect Google and allow Gmail")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Couldn't sync Gmail: a Gmail sync is already running"),
    );
  });

  it("offers Retry when the list fails to load", async () => {
    vi.mocked(listSuggestions).mockRejectedValueOnce(new ApiError(500, "boom"));
    render(Email);
    await fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Thank you for applying to Acme")).toBeInTheDocument();
  });
});
