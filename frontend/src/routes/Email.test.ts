import { fireEvent, render, screen, within } from "@testing-library/svelte";
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
import { acceptSuggestion, dismissSuggestion, getEmailStatus, listSuggestions, syncEmailNow } from "../lib/api/email";
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
  vi.mocked(acceptSuggestion).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("Email updates page", () => {
  it("lists the pending updates first, with the count on the tab", async () => {
    render(Email);
    expect(screen.getByRole("heading", { name: "Email updates" })).toBeInTheDocument();
    expect(await screen.findByText("Thank you for applying to Acme")).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenCalledWith({ state: "pending", limit: 200 });
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

  it("drops a decided card at once, before the reload answers", async () => {
    vi.mocked(dismissSuggestion).mockResolvedValue(fakeSuggestion({ id: 1, state: "dismissed" }));
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    vi.mocked(listSuggestions).mockReturnValue(new Promise(() => {})); // the reload never answers
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await vi.waitFor(() => expect(screen.queryByText("Thank you for applying to Acme")).toBeNull());
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("a stale card (409) is reloaded away", async () => {
    vi.mocked(acceptSuggestion).mockRejectedValue(new ApiError(409, "this suggestion no longer applies"));
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    vi.mocked(listSuggestions).mockResolvedValue([]);
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByText("No email updates to review.")).toBeInTheDocument();
  });

  it("says when more are pending than the list shows", async () => {
    const rows = Array.from({ length: 200 }, (_, i) => fakeSuggestion({ id: i + 1, subject: `Update ${i + 1}` }));
    vi.mocked(listSuggestions).mockResolvedValue(rows);
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 230 }));
    render(Email);
    expect(await screen.findByText("Showing the first 200 of 230.")).toBeInTheDocument();
  });

  it("doesn't say so when the whole list is shown", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 1 }));
    render(Email);
    await screen.findByText("Thank you for applying to Acme");
    await vi.waitFor(() => expect(screen.getAllByRole("tab")[0]).toHaveTextContent("Pending (1)"));
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("says when the Gmail status can't be loaded, with Retry", async () => {
    vi.mocked(getEmailStatus).mockRejectedValueOnce(new ApiError(500, "boom"));
    render(Email);
    const sync = screen.getByRole("region", { name: "Gmail sync" });
    expect(await within(sync).findByText(/Couldn't load Gmail status/)).toBeInTheDocument();
    await fireEvent.click(within(sync).getByRole("button", { name: "Retry" }));
    expect(await within(sync).findByRole("button", { name: "Sync now" })).toBeInTheDocument();
    expect(within(sync).queryByText(/Couldn't load Gmail status/)).toBeNull();
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

  it("says Connect when sync is on but no inbox is connected", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ gmailGranted: false, gmailSyncEnabled: true }));
    vi.mocked(listSuggestions).mockResolvedValue([]);
    render(Email);
    expect(await screen.findByRole("link", { name: "Connect Gmail in Settings" })).toBeInTheDocument();
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
