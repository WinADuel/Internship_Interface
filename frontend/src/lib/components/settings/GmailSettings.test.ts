import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../api/email", () => ({
  CONNECT_GMAIL_URL: "/api/docs/google/authorize?gmail=1",
  getEmailStatus: vi.fn(),
  syncEmailNow: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getEmailStatus, syncEmailNow } from "../../api/email";
import { updateSettings } from "../../api/settings";
import { showToast } from "../../stores/toast";
import { fakeEmailStatus } from "../../testing/fixtures";
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
});

describe("GmailSettings", () => {
  it("offers Connect Gmail, explains what is stored, and can't sync yet", () => {
    render(GmailSettings, { settings: settings() });
    const connect = screen.getByRole("link", { name: "Connect Gmail" });
    expect(connect.getAttribute("href")).toBe("/api/docs/google/authorize?gmail=1");
    const section = screen.getByRole("region", { name: "Gmail" });
    expect(section).toHaveTextContent("message bodies are never downloaded");
    expect(section).toHaveTextContent("Optional and off by default");
    expect(section).toHaveTextContent("Google hasn't verified this app");
    expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
    expect(section).toHaveTextContent("Connect Gmail first, then turn on Sync Gmail.");
    expect(section).toHaveTextContent("Last sync: never");
  });

  it("shows Connected once Gmail is granted, and the auto-apply explanation", () => {
    render(GmailSettings, { settings: settings({ gmailGranted: true }) });
    expect(screen.getByText("Gmail: Connected")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect Gmail" })).toBeNull();
    expect(screen.getByText(/rejections, interviews, assessments and offers always wait for you/)).toBeInTheDocument();
    expect(screen.getByText("Turn on Sync Gmail and save to sync.")).toBeInTheDocument();
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
      ...fakeEmailStatus({ gmailLastSyncAt: "2026-10-09T09:00:00Z" }),
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
  });

  it("shows the last error with a Reconnect link", () => {
    render(GmailSettings, {
      settings: settings({ gmailGranted: true, gmailSyncEnabled: true, gmailLastError: "reconnect Google and allow Gmail" }),
    });
    expect(screen.getByText("Last sync failed: reconnect Google and allow Gmail")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconnect Gmail" }).getAttribute("href")).toBe(
      "/api/docs/google/authorize?gmail=1",
    );
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
