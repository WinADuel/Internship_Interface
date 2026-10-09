import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api/settings", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  listClaudeTokens: vi.fn(),
  createClaudeToken: vi.fn(),
  revokeClaudeToken: vi.fn(),
  syncSheetNow: vi.fn(),
}));
vi.mock("../lib/api/discovery", () => ({ getMatchCount: vi.fn() }));
vi.mock("../lib/api/backups", () => ({ getBackupStatus: vi.fn(), runBackupNow: vi.fn() }));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import { getBackupStatus } from "../lib/api/backups";
import { getMatchCount } from "../lib/api/discovery";
import { getSettings, listClaudeTokens, updateSettings } from "../lib/api/settings";
import { showToast } from "../lib/stores/toast";
import type { AppSettings } from "../lib/types/contact";
import Settings from "./Settings.svelte";

const settings: AppSettings = {
  outreachProfile: "CS junior",
  nudgeUnsentDays: 5,
  nudgeFollowupDays: 10,
  nudgeGoneQuietDays: 10,
  nudgeRepliedStaleDays: 14,
  claudeJobMaxItems: 8,
  backupSheetId: null,
  lastSheetSyncAt: null,
  lastSheetSyncError: null,
  discoveryListUrls: [],
  discoveryTerms: ["Summer 2027"],
  discoveryCategories: ["Software"],
  discoveryIncludeKeywords: [],
  discoveryWatchlistKeywords: ["intern"],
  discoveryExcludeKeywords: [],
  discoveryLocations: [],
  discoveryHideNoSponsorship: false,
  discoveryScanHours: 6,
  lastScanAt: null,
  lastScanError: null,
  rankingRoleKeywords: [],
  rankingSkillKeywords: [],
  rankingPreferredLocations: [],
  rankingPreferredCompanies: [],
  rankingAvoidCompanies: [],
  rankingDealbreakerKeywords: [],
  rankingClaudeDailyLimit: 40,
  rankingUpdatedAt: null,
};

beforeEach(() => {
  vi.mocked(getSettings).mockReset().mockResolvedValue(settings);
  vi.mocked(updateSettings).mockReset();
  vi.mocked(listClaudeTokens).mockReset().mockResolvedValue([]);
  vi.mocked(showToast).mockReset();
  vi.mocked(getMatchCount).mockReset().mockResolvedValue(3);
  vi.mocked(getBackupStatus).mockReset().mockResolvedValue({
    lastBackupAt: null, lastBackupError: null, lastOffsiteAt: null, lastOffsiteError: null, offsiteConfigured: true,
  });
});

describe("Settings page", () => {
  it("loads the settings and saves every field with one Save", async () => {
    vi.mocked(updateSettings).mockResolvedValue({ ...settings, outreachProfile: "ML junior", nudgeUnsentDays: 3 });
    render(Settings);
    const profile = (await screen.findByLabelText("Outreach profile")) as HTMLTextAreaElement;
    await vi.waitFor(() => expect(profile.value).toBe("CS junior"));
    expect(profile.placeholder).toBe(
      "Your background, interests, and what you're looking for — Claude uses this to personalize every draft.",
    );
    await fireEvent.input(profile, { target: { value: "ML junior" } });
    await fireEvent.input(screen.getByLabelText("Unsent draft nudge (days)"), { target: { value: "3" } });
    await fireEvent.submit(screen.getByRole("form", { name: "Outreach settings" }));
    expect(updateSettings).toHaveBeenCalledWith({
      outreachProfile: "ML junior",
      nudgeUnsentDays: 3,
      nudgeFollowupDays: 10,
      nudgeGoneQuietDays: 10,
      nudgeRepliedStaleDays: 14,
      claudeJobMaxItems: 8,
    });
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Settings saved.", "info"));
  });

  it("bounds the number inputs", async () => {
    render(Settings);
    await screen.findByLabelText("Outreach profile");
    for (const label of [
      "Unsent draft nudge (days)",
      "Follow-up due after (days)",
      "Gone quiet after (days)",
      "Unanswered reply nudge (days)",
    ]) {
      const input = screen.getByLabelText(label) as HTMLInputElement;
      expect([input.min, input.max, input.required]).toEqual(["1", "90", true]);
    }
    const max = screen.getByLabelText("Max items per daily run") as HTMLInputElement;
    expect([max.min, max.max]).toEqual(["1", "25"]);
  });

  it("shows a load error with Retry instead of a dead page", async () => {
    vi.mocked(getSettings).mockRejectedValueOnce(new Error("offline"));
    render(Settings);
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load settings");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect((screen.getByLabelText("Outreach profile") as HTMLTextAreaElement).value).toBe("CS junior");
  });

  it("a failed save shows a toast", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new Error("db down"));
    render(Settings);
    await vi.waitFor(() => expect((screen.getByLabelText("Outreach profile") as HTMLTextAreaElement).value).toBe("CS junior"));
    await fireEvent.submit(screen.getByRole("form", { name: "Outreach settings" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't save settings."));
  });

  it("has a Job discovery section that saves on its own, keeping unsaved outreach edits", async () => {
    vi.mocked(updateSettings).mockResolvedValue({ ...settings, discoveryTerms: ["Summer 2027", "Fall 2027"] });
    render(Settings);
    const discovery = await screen.findByRole("form", { name: "Job discovery settings" });
    const profile = screen.getByLabelText("Outreach profile") as HTMLTextAreaElement;
    await vi.waitFor(() => expect(profile.value).toBe("CS junior"));
    await fireEvent.input(profile, { target: { value: "unsaved edit" } });

    const terms = screen.getByLabelText("Terms");
    await fireEvent.input(terms, { target: { value: "Fall 2027" } });
    await fireEvent.keyDown(terms, { key: "Enter" });
    await fireEvent.submit(discovery);

    expect(updateSettings).toHaveBeenCalledTimes(1);
    const body = vi.mocked(updateSettings).mock.calls[0][0];
    expect(Object.keys(body).every((k) => k.startsWith("discovery"))).toBe(true);
    expect(body.discoveryTerms).toEqual(["Summer 2027", "Fall 2027"]);
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Job discovery settings saved.", "info"));
    expect(profile.value).toBe("unsaved edit");
  });

  it("shows the Backups card right after the backup-sheet card", async () => {
    render(Settings);
    await screen.findByRole("heading", { name: "Backup sheet" });
    await screen.findByText("Last backup: No backup yet");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings.slice(-2)).toEqual(["Backup sheet", "Backups"]);
    expect(getBackupStatus).toHaveBeenCalledTimes(1);
  });
});
