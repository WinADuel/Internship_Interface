import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../api/email", () => ({
  CONNECT_GMAIL_URL: "/api/docs/google/authorize?gmail=1",
  getEmailStatus: vi.fn(),
  syncEmailNow: vi.fn(),
  listGmailAccounts: vi.fn(),
  removeGmailAccount: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getEmailStatus, listGmailAccounts, removeGmailAccount, syncEmailNow } from "../../api/email";
import { updateSettings } from "../../api/settings";
import { showToast } from "../../stores/toast";
import { fakeEmailStatus, fakeGmailAccount } from "../../testing/fixtures";
import type { AppSettings } from "../../types/contact";
import GmailSettings from "./GmailSettings.svelte";

const base = {
  gmailSyncEnabled: false,
  gmailSyncMinutes: 30,
  gmailLookbackDays: 30,
  gmailAutoApply: false,
  gmailLastSyncAt: null,
  gmailLastError: null,
  googleConnected: true,
  gmailGranted: false,
} as const;
const settings = (overrides: Partial<AppSettings> = {}) => ({ ...base, ...overrides }) as AppSettings;

beforeEach(() => {
  vi.mocked(updateSettings).mockReset();
  vi.mocked(syncEmailNow).mockReset();
  vi.mocked(getEmailStatus).mockReset().mockResolvedValue(fakeEmailStatus());
  vi.mocked(showToast).mockReset();
  vi.mocked(listGmailAccounts).mockReset().mockResolvedValue([]);
  vi.mocked(removeGmailAccount).mockReset();
});

afterEach(() => vi.restoreAllMocks());

const personal = fakeGmailAccount({ id: 1, email: "me@gmail.com", lastSyncAt: "2026-10-09T08:00:00Z" });
const school = fakeGmailAccount({ id: 2, email: "you@school.edu", lastError: "reconnect this inbox in Settings" });

describe("GmailSettings", () => {
  it("offers Connect Gmail, explains what is stored, and can't sync yet", () => {
    render(GmailSettings, { settings: settings() });
    const connect = screen.getByRole("link", { name: "Connect Gmail" });
    expect(connect.getAttribute("href")).toBe("/api/docs/google/authorize?gmail=1");
    const section = screen.getByRole("region", { name: "Gmail" });
    expect(section).toHaveTextContent("Message bodies are never downloaded");
    expect(section).toHaveTextContent("from a company you don't track yet");
    expect(section).toHaveTextContent("Optional and off by default");
    expect(section).toHaveTextContent("Google hasn't verified this app");
    expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
    expect(section).toHaveTextContent("Connect Gmail first, then turn on Sync Gmail.");
    expect(section).toHaveTextContent("Last sync: never");
  });

  it("lists the connected inboxes with their last sync, error, Reconnect and Remove, and offers another", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValue([personal, school]);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    const list = await screen.findByRole("list", { name: "Inboxes" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("me@gmail.com");
    expect(rows[0]).not.toHaveTextContent("Last sync: never");
    expect(rows[1]).toHaveTextContent("you@school.edu");
    expect(rows[1]).toHaveTextContent("Last sync: never");
    expect(rows[1]).toHaveTextContent("reconnect this inbox in Settings");
    expect(within(rows[1]).getByRole("link", { name: "Reconnect you@school.edu" }).getAttribute("href")).toBe(
      "/api/docs/google/authorize?gmail=1",
    );
    expect(within(rows[1]).getByRole("button", { name: "Remove you@school.edu" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add another inbox" }).getAttribute("href")).toBe(
      "/api/docs/google/authorize?gmail=1",
    );
    expect(screen.queryByRole("link", { name: "Connect Gmail" })).toBeNull();
    expect(screen.getByText(/doesn't withdraw the app's access at Google/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "myaccount.google.com/permissions" }).getAttribute("href")).toBe(
      "https://myaccount.google.com/permissions",
    );
    expect(screen.getByText(/rejections, interviews, assessments and offers always wait for you/)).toBeInTheDocument();
    expect(screen.getByText("Turn on Sync Gmail and save to sync.")).toBeInTheDocument();
  });

  it("names an inbox carried over from before its address was read", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValue([fakeGmailAccount({ email: null })]);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    expect(await screen.findByText("Gmail inbox, address shown after the next sync")).toBeInTheDocument();
  });

  it("Remove asks first, then removes the inbox and refreshes the email status", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValue([personal, school]);
    vi.mocked(removeGmailAccount).mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    const remove = await screen.findByRole("button", { name: "Remove you@school.edu" });
    await fireEvent.click(remove);
    expect(confirm).toHaveBeenCalledWith(
      "Remove you@school.edu? Its email updates are deleted from the tracker. Changes you already accepted stay.",
    );
    expect(removeGmailAccount).not.toHaveBeenCalled();
    await fireEvent.click(remove);
    expect(removeGmailAccount).toHaveBeenCalledWith(2);
    await vi.waitFor(() => expect(screen.queryByText("you@school.edu")).toBeNull());
    expect(screen.getByText("me@gmail.com")).toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith("Removed you@school.edu.", "info");
    expect(getEmailStatus).toHaveBeenCalled();
  });

  it("removing the last inbox offers Connect Gmail again and can't sync", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValue([personal]);
    vi.mocked(removeGmailAccount).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(GmailSettings, { settings: settings({ gmailGranted: true, gmailSyncEnabled: true }) });
    expect(screen.getByRole("button", { name: "Sync now" })).not.toBeDisabled();
    await fireEvent.click(await screen.findByRole("button", { name: "Remove me@gmail.com" }));
    expect(await screen.findByRole("link", { name: "Connect Gmail" })).toBeInTheDocument();
    expect(screen.getByText("No inbox connected.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
  });

  it("a failed Remove keeps the inbox and says why", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValue([personal]);
    vi.mocked(removeGmailAccount).mockRejectedValue(new ApiError(500, "boom"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove me@gmail.com" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't remove the inbox: boom"));
    expect(screen.getByText("me@gmail.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove me@gmail.com" })).not.toBeDisabled();
  });

  it("an inbox already removed elsewhere (404) reloads the list", async () => {
    vi.mocked(listGmailAccounts).mockResolvedValueOnce([personal, school]).mockResolvedValueOnce([personal]);
    vi.mocked(removeGmailAccount).mockRejectedValue(new ApiError(404, "Gmail inbox not found"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove you@school.edu" }));
    await vi.waitFor(() => expect(screen.queryByText("you@school.edu")).toBeNull());
    expect(listGmailAccounts).toHaveBeenCalledTimes(2);
  });

  it("a list that answers after a removal doesn't bring the inbox back", async () => {
    let answer!: (rows: ReturnType<typeof fakeGmailAccount>[]) => void;
    vi.mocked(listGmailAccounts)
      .mockResolvedValueOnce([personal, school])
      .mockReturnValueOnce(new Promise((r) => (answer = r)));
    vi.mocked(removeGmailAccount).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    await screen.findByText("you@school.edu");
    // A 404 reloads the list; another removal lands before that list answers.
    vi.mocked(removeGmailAccount).mockRejectedValueOnce(new ApiError(404, "gone"));
    await fireEvent.click(screen.getByRole("button", { name: "Remove me@gmail.com" }));
    await vi.waitFor(() => expect(listGmailAccounts).toHaveBeenCalledTimes(2));
    await fireEvent.click(screen.getByRole("button", { name: "Remove you@school.edu" }));
    await vi.waitFor(() => expect(screen.queryByText("you@school.edu")).toBeNull());
    answer([personal, school]);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText("me@gmail.com")).toBeInTheDocument();
    expect(screen.queryByText("you@school.edu")).toBeNull();
  });

  it("shows a failed inbox list with Retry", async () => {
    vi.mocked(listGmailAccounts).mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce([personal]);
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    await fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("me@gmail.com")).toBeInTheDocument();
  });

  it("bounds the interval and lookback", () => {
    render(GmailSettings, { settings: settings() });
    const minutes = screen.getByLabelText("Check every (minutes)") as HTMLInputElement;
    const lookback = screen.getByLabelText("First sync looks back (days)") as HTMLInputElement;
    expect([minutes.min, minutes.max, minutes.value]).toEqual(["15", "240", "30"]);
    expect([lookback.min, lookback.max, lookback.value]).toEqual(["1", "90", "30"]);
  });

  it("saves the four Gmail fields and reports the saved settings", async () => {
    const saved = settings({ gmailSyncEnabled: true, gmailSyncMinutes: 60, gmailAutoApply: true });
    vi.mocked(updateSettings).mockResolvedValue(saved);
    const onsaved = vi.fn();
    render(GmailSettings, { settings: settings(), onsaved });
    await fireEvent.click(screen.getByLabelText("Sync Gmail"));
    await fireEvent.input(screen.getByLabelText("Check every (minutes)"), { target: { value: "60" } });
    await fireEvent.click(screen.getByLabelText("Apply some updates automatically"));
    await fireEvent.submit(screen.getByRole("form", { name: "Gmail settings" }));
    expect(updateSettings).toHaveBeenCalledWith({
      gmailSyncEnabled: true,
      gmailSyncMinutes: 60,
      gmailLookbackDays: 30,
      gmailAutoApply: true,
    });
    await vi.waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(showToast).toHaveBeenCalledWith("Gmail settings saved.", "info");
  });

  it("refuses an interval out of range before sending", async () => {
    render(GmailSettings, { settings: settings() });
    await fireEvent.input(screen.getByLabelText("Check every (minutes)"), { target: { value: "5" } });
    await fireEvent.submit(screen.getByRole("form", { name: "Gmail settings" }));
    expect(screen.getByRole("alert")).toHaveTextContent("from 15 to 240");
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("shows a server refusal", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new ApiError(422, "gmail_lookback_days: too big"));
    render(GmailSettings, { settings: settings() });
    await fireEvent.submit(screen.getByRole("form", { name: "Gmail settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save Gmail settings: gmail_lookback_days: too big");
  });

  it("Sync now runs a sync and shows the outcome", async () => {
    vi.mocked(syncEmailNow).mockResolvedValue({
      ...fakeEmailStatus({ gmailLastSyncAt: "2026-10-09T09:00:00Z", accounts: [fakeGmailAccount({ email: "learned@gmail.com", lastSyncAt: "2026-10-09T09:00:00Z" })] }),
      ok: true,
      fetched: 5,
      suggested: 2,
      autoApplied: 1,
      more: false,
    });
    render(GmailSettings, { settings: settings({ gmailGranted: true, gmailSyncEnabled: true }) });
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    expect(await screen.findByText("Checked 5 emails: 2 updates found, 1 applied automatically.")).toBeInTheDocument();
    expect(screen.queryByText("Last sync: never")).toBeNull();
    // The inboxes as the sync left them (a carried-over inbox learns its address).
    expect(screen.getByText("learned@gmail.com")).toBeInTheDocument();
  });

  it("with no inbox left, shows the run's last error and offers Connect Gmail", async () => {
    render(GmailSettings, {
      settings: settings({
        gmailGranted: false,
        gmailSyncEnabled: true,
        gmailLastError: "you@school.edu: reconnect this inbox in Settings",
      }),
    });
    expect(screen.getByText("Last sync failed: you@school.edu: reconnect this inbox in Settings")).toBeInTheDocument();
    expect(await screen.findByText("No inbox connected.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Gmail" }).getAttribute("href")).toBe("/api/docs/google/authorize?gmail=1");
    expect(screen.queryByRole("link", { name: "Add another inbox" })).toBeNull();
  });

  it("a refused Sync now is a toast", async () => {
    vi.mocked(syncEmailNow).mockRejectedValue(new ApiError(400, "turn on Gmail sync in Settings first"));
    render(GmailSettings, { settings: settings({ gmailGranted: true, gmailSyncEnabled: true }) });
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Couldn't sync Gmail: turn on Gmail sync in Settings first"),
    );
  });
});
