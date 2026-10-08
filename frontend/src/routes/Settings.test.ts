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
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

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
};

beforeEach(() => {
  vi.mocked(getSettings).mockReset().mockResolvedValue(settings);
  vi.mocked(updateSettings).mockReset();
  vi.mocked(listClaudeTokens).mockReset().mockResolvedValue([]);
  vi.mocked(showToast).mockReset();
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
});
