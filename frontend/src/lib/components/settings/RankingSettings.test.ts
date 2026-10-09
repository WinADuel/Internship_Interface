import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({ getTopPicksCount: vi.fn() }));
vi.mock("../../api/settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getTopPicksCount } from "../../api/discovery";
import { updateSettings } from "../../api/settings";
import { showToast } from "../../stores/toast";
import type { AppSettings } from "../../types/contact";
import RankingSettings from "./RankingSettings.svelte";

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
  discoveryCategories: [],
  discoveryIncludeKeywords: [],
  discoveryWatchlistKeywords: [],
  discoveryExcludeKeywords: [],
  discoveryLocations: [],
  discoveryHideNoSponsorship: false,
  discoveryScanHours: 6,
  lastScanAt: null,
  lastScanError: null,
  rankingRoleKeywords: ["machine learning"],
  rankingSkillKeywords: ["python"],
  rankingPreferredLocations: ["New York"],
  rankingPreferredCompanies: [],
  rankingAvoidCompanies: ["Initech"],
  rankingDealbreakerKeywords: ["unpaid"],
  rankingClaudeDailyLimit: 40,
  rankingUpdatedAt: "2026-10-09T08:00:00Z",
};

const PREFS = {
  rankingRoleKeywords: ["machine learning"],
  rankingSkillKeywords: ["python"],
  rankingPreferredLocations: ["New York"],
  rankingPreferredCompanies: [],
  rankingAvoidCompanies: ["Initech"],
  rankingDealbreakerKeywords: ["unpaid"],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

async function addChip(label: string, value: string) {
  const input = screen.getByLabelText(label);
  await fireEvent.input(input, { target: { value } });
  await fireEvent.keyDown(input, { key: "Enter" });
}

const form = () => screen.getByRole("form", { name: "Ranking preferences" });
const limit = () => screen.getByLabelText("Postings Claude reviews per day") as HTMLInputElement;

beforeEach(() => {
  vi.mocked(getTopPicksCount).mockReset().mockResolvedValue(12);
  vi.mocked(updateSettings).mockReset();
  vi.mocked(showToast).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RankingSettings", () => {
  it("shows the saved preferences and the daily Claude limit", () => {
    render(RankingSettings, { settings });
    expect(screen.getByRole("heading", { name: "Ranking" })).toBeInTheDocument();
    for (const value of ["machine learning", "python", "New York", "Initech", "unpaid"]) {
      expect(screen.getByText(value)).toBeInTheDocument();
    }
    expect(limit().value).toBe("40");
    expect([limit().min, limit().max, limit().required]).toEqual(["0", "150", true]);
    expect(screen.getByText(/0 turns Claude ranking off/)).toBeInTheDocument();
  });

  it("caps keywords at 60 characters like the backend", async () => {
    render(RankingSettings, { settings });
    await addChip("Role keywords", "x".repeat(61));
    expect(screen.queryByText("x".repeat(61))).toBeNull();
  });

  it("saves only the ranking fields, with the edits, and toasts", async () => {
    const saved = { ...settings, rankingPreferredCompanies: ["Stripe"], rankingClaudeDailyLimit: 0 };
    vi.mocked(updateSettings).mockResolvedValue(saved);
    const onsaved = vi.fn();
    render(RankingSettings, { settings, onsaved });
    await addChip("Preferred companies", "Stripe");
    await addChip("Preferred companies", "stripe"); // duplicate: ignored
    await fireEvent.click(screen.getByRole("button", { name: "Remove python from Skill keywords" }));
    await fireEvent.input(limit(), { target: { value: "0" } });
    await fireEvent.submit(form());

    expect(updateSettings).toHaveBeenCalledWith({
      ...PREFS,
      rankingSkillKeywords: [],
      rankingPreferredCompanies: ["Stripe"],
      rankingClaudeDailyLimit: 0,
    });
    await vi.waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(showToast).toHaveBeenCalledWith("Ranking preferences saved. The Inbox has been re-scored.", "info");
  });

  it("saves text typed into a chip field but not yet added", async () => {
    vi.mocked(updateSettings).mockResolvedValue(settings);
    render(RankingSettings, { settings });
    await fireEvent.input(screen.getByLabelText("Dealbreaker keywords"), { target: { value: "clearance" } });
    await fireEvent.submit(form());
    expect(vi.mocked(updateSettings).mock.calls[0][0].rankingDealbreakerKeywords).toEqual(["unpaid", "clearance"]);
  });

  it("shows 422 field errors next to their fields", async () => {
    vi.mocked(updateSettings).mockRejectedValue(
      new ApiError(422, [
        { loc: ["body", "ranking_role_keywords"], msg: "Value error, at most 30 items", type: "value_error" },
        {
          loc: ["body", "ranking_claude_daily_limit"],
          msg: "Input should be less than or equal to 150",
          type: "less_than_equal",
        },
      ]),
    );
    render(RankingSettings, { settings });
    await fireEvent.submit(form());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some preferences weren't saved. Fix the fields marked below.",
    );
    expect(screen.getByText("at most 30 items")).toBeInTheDocument();
    expect(screen.getByLabelText("Role keywords")).toHaveAttribute("aria-invalid", "true");
    expect(limit()).toHaveAttribute("aria-invalid", "true");
    expect(limit().getAttribute("aria-describedby")).toBe("ranking-daily-limit-hint ranking-daily-limit-error");
    expect(showToast).not.toHaveBeenCalled();
  });

  it("shows any other save failure inline", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new ApiError(500, "db down"));
    render(RankingSettings, { settings });
    await fireEvent.submit(form());
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save ranking preferences: db down");
  });
});

describe("RankingSettings live Top picks count", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("counts Top picks for the current lists 400 ms after they settle", async () => {
    render(RankingSettings, { settings });
    expect(screen.getByRole("status")).toHaveTextContent("Counting Top picks…");
    await vi.advanceTimersByTimeAsync(399);
    expect(getTopPicksCount).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(getTopPicksCount).toHaveBeenCalledWith(PREFS);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("Top picks now: 12");
  });

  it("debounces edits into one request with the latest lists, and ignores the daily limit", async () => {
    render(RankingSettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    vi.mocked(getTopPicksCount).mockClear().mockResolvedValue(3);
    await addChip("Role keywords", "backend");
    await vi.advanceTimersByTimeAsync(200);
    await addChip("Preferred locations", "Remote");
    await fireEvent.input(limit(), { target: { value: "10" } });
    await vi.advanceTimersByTimeAsync(399);
    expect(getTopPicksCount).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(getTopPicksCount).toHaveBeenCalledTimes(1);
    expect(getTopPicksCount).toHaveBeenCalledWith({
      ...PREFS,
      rankingRoleKeywords: ["machine learning", "backend"],
      rankingPreferredLocations: ["New York", "Remote"],
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("Top picks now: 3");
  });

  it("only the latest request's answer is shown when answers arrive out of order", async () => {
    const first = deferred<number>();
    const second = deferred<number>();
    vi.mocked(getTopPicksCount).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(RankingSettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    await addChip("Skill keywords", "go");
    await vi.advanceTimersByTimeAsync(400);
    second.resolve(5);
    await vi.advanceTimersByTimeAsync(0);
    first.resolve(99);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("Top picks now: 5");
  });

  it("a failed count is a quiet note, not an alert", async () => {
    vi.mocked(getTopPicksCount).mockRejectedValue(new ApiError(500, "boom"));
    render(RankingSettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't count Top picks.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("stops counting once unmounted", async () => {
    const { unmount } = render(RankingSettings, { settings });
    unmount();
    await vi.advanceTimersByTimeAsync(1000);
    expect(getTopPicksCount).not.toHaveBeenCalled();
  });
});
