import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({ getMatchCount: vi.fn() }));
vi.mock("../../api/settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getMatchCount } from "../../api/discovery";
import { updateSettings } from "../../api/settings";
import { showToast } from "../../stores/toast";
import type { AppSettings } from "../../types/contact";
import DiscoverySettings from "./DiscoverySettings.svelte";

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
  discoveryListUrls: ["https://raw.githubusercontent.com/a/b/listings.json"],
  discoveryTerms: ["Summer 2027"],
  discoveryCategories: ["Software"],
  discoveryIncludeKeywords: [],
  discoveryWatchlistKeywords: ["intern", "co-op"],
  discoveryExcludeKeywords: ["senior", "phd"],
  discoveryLocations: [],
  discoveryHideNoSponsorship: false,
  discoveryScanHours: 6,
  lastScanAt: null,
  lastScanError: null,
};

const FILTERS = {
  discoveryTerms: ["Summer 2027"],
  discoveryCategories: ["Software"],
  discoveryIncludeKeywords: [],
  discoveryWatchlistKeywords: ["intern", "co-op"],
  discoveryExcludeKeywords: ["senior", "phd"],
  discoveryLocations: [],
  discoveryHideNoSponsorship: false,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function addChip(label: string, value: string) {
  const input = screen.getByLabelText(label);
  await fireEvent.input(input, { target: { value } });
  await fireEvent.keyDown(input, { key: "Enter" });
}

const form = () => screen.getByRole("form", { name: "Job discovery settings" });

beforeEach(() => {
  vi.mocked(getMatchCount).mockReset().mockResolvedValue(12);
  vi.mocked(updateSettings).mockReset();
  vi.mocked(showToast).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DiscoverySettings", () => {
  it("shows every filter from the saved settings", () => {
    render(DiscoverySettings, { settings });
    expect(screen.getByRole("heading", { name: "Job discovery" })).toBeInTheDocument();
    expect(screen.getByText("Summer 2027")).toBeInTheDocument();
    expect(screen.getByText("senior")).toBeInTheDocument();
    expect((screen.getByLabelText("Hide postings that don't offer sponsorship") as HTMLInputElement).checked).toBe(false);
    const hours = screen.getByLabelText("Scan every (hours)") as HTMLInputElement;
    expect(hours.value).toBe("6");
    expect([hours.min, hours.max, hours.required]).toEqual(["1", "48", true]);
    // List URLs are advanced: tucked in a closed <details>.
    const details = screen.getByText("Advanced: community list URLs").closest("details");
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false);
    expect(within(details!).getByText("https://raw.githubusercontent.com/a/b/listings.json")).toBeInTheDocument();
  });

  it("offers the five Simplify categories as suggestions", () => {
    render(DiscoverySettings, { settings });
    for (const c of ["AI/ML/Data", "Hardware", "Product", "Quant"]) {
      expect(screen.getByRole("button", { name: `Add ${c} to Categories` })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Add Software to Categories" })).toBeNull();
  });

  it("refuses a non-https list URL before saving", async () => {
    render(DiscoverySettings, { settings });
    await addChip("List URLs", "http://example.com/listings.json");
    expect(screen.getByText("List URLs must start with https://.")).toBeInTheDocument();
  });

  it("saves only the discovery fields, with the edits", async () => {
    const saved = { ...settings, discoveryCategories: ["Software", "Quant"], discoveryLocations: ["Remote"] };
    vi.mocked(updateSettings).mockResolvedValue(saved);
    const onsaved = vi.fn();
    render(DiscoverySettings, { settings, onsaved });
    await fireEvent.click(screen.getByRole("button", { name: "Add Quant to Categories" }));
    await addChip("Locations", "Remote");
    await addChip("Locations", "remote"); // duplicate: ignored
    await fireEvent.click(screen.getByRole("button", { name: "Remove phd from Exclude keywords" }));
    await fireEvent.click(screen.getByLabelText("Hide postings that don't offer sponsorship"));
    await fireEvent.input(screen.getByLabelText("Scan every (hours)"), { target: { value: "12" } });
    await fireEvent.submit(form());

    expect(updateSettings).toHaveBeenCalledTimes(1);
    expect(updateSettings).toHaveBeenCalledWith({
      discoveryListUrls: ["https://raw.githubusercontent.com/a/b/listings.json"],
      discoveryTerms: ["Summer 2027"],
      discoveryCategories: ["Software", "Quant"],
      discoveryIncludeKeywords: [],
      discoveryWatchlistKeywords: ["intern", "co-op"],
      discoveryExcludeKeywords: ["senior"],
      discoveryLocations: ["Remote"],
      discoveryHideNoSponsorship: true,
      discoveryScanHours: 12,
    });
    await vi.waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(showToast).toHaveBeenCalledWith("Job discovery settings saved.", "info");
  });

  it("shows 422 field errors next to their fields", async () => {
    vi.mocked(updateSettings).mockRejectedValue(
      new ApiError(422, [
        { loc: ["body", "discovery_terms"], msg: "Value error, at most 30 items", type: "value_error" },
        { loc: ["body", "discovery_scan_hours"], msg: "Input should be less than or equal to 48", type: "less_than_equal" },
      ]),
    );
    render(DiscoverySettings, { settings });
    await fireEvent.submit(form());
    expect(await screen.findByRole("alert")).toHaveTextContent("Some settings weren't saved. Fix the fields marked below.");
    expect(screen.getByText("at most 30 items")).toBeInTheDocument();
    expect(screen.getByLabelText("Terms")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Input should be less than or equal to 48")).toBeInTheDocument();
    expect(screen.getByLabelText("Scan every (hours)")).toHaveAttribute("aria-invalid", "true");
    expect(showToast).not.toHaveBeenCalled();
  });

  it("shows any other save failure inline", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new ApiError(500, "db down"));
    render(DiscoverySettings, { settings });
    await fireEvent.submit(form());
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save job discovery settings: db down");
  });
});

describe("DiscoverySettings live match count", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("counts the current filters 400 ms after they settle", async () => {
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(399);
    expect(getMatchCount).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(getMatchCount).toHaveBeenCalledTimes(1);
    expect(getMatchCount).toHaveBeenCalledWith(FILTERS);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("12 postings match");
  });

  it("debounces a burst of edits into one request with the latest filters", async () => {
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    vi.mocked(getMatchCount).mockClear().mockResolvedValue(1);
    await addChip("Locations", "Remote");
    await vi.advanceTimersByTimeAsync(200);
    await addChip("Locations", "NYC");
    await vi.advanceTimersByTimeAsync(200);
    await fireEvent.click(screen.getByLabelText("Hide postings that don't offer sponsorship"));
    await vi.advanceTimersByTimeAsync(399);
    expect(getMatchCount).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(getMatchCount).toHaveBeenCalledTimes(1);
    expect(getMatchCount).toHaveBeenCalledWith({
      ...FILTERS,
      discoveryLocations: ["Remote", "NYC"],
      discoveryHideNoSponsorship: true,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("1 posting matches");
  });

  it("only the latest request's answer is shown when answers arrive out of order", async () => {
    const first = deferred<number>();
    const second = deferred<number>();
    vi.mocked(getMatchCount).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    await addChip("Locations", "Remote");
    await vi.advanceTimersByTimeAsync(400);
    expect(getMatchCount).toHaveBeenCalledTimes(2);

    second.resolve(5);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("5 postings match");
    first.resolve(99); // stale: older filters
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("5 postings match");
    expect(screen.queryByText(/99/)).toBeNull();
  });

  it("ignores a stale failure too", async () => {
    const first = deferred<number>();
    vi.mocked(getMatchCount).mockReturnValueOnce(first.promise).mockResolvedValueOnce(7);
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    await addChip("Terms", "Fall 2027");
    await vi.advanceTimersByTimeAsync(400);
    expect(screen.getByRole("status")).toHaveTextContent("7 postings match");
    first.reject(new ApiError(500, "boom"));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toHaveTextContent("7 postings match");
  });

  it("a failed count is a quiet note, not an alert", async () => {
    vi.mocked(getMatchCount).mockRejectedValue(new ApiError(500, "boom"));
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't count matching postings.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(showToast).not.toHaveBeenCalled();
  });

  it("does not recount for settings that aren't filters", async () => {
    render(DiscoverySettings, { settings });
    await vi.advanceTimersByTimeAsync(400);
    expect(getMatchCount).toHaveBeenCalledTimes(1);
    await fireEvent.input(screen.getByLabelText("Scan every (hours)"), { target: { value: "3" } });
    await addChip("List URLs", "https://example.com/listings.json");
    await vi.advanceTimersByTimeAsync(1000);
    expect(getMatchCount).toHaveBeenCalledTimes(1);
  });

  it("stops counting once unmounted", async () => {
    const { unmount } = render(DiscoverySettings, { settings });
    unmount();
    await vi.advanceTimersByTimeAsync(1000);
    expect(getMatchCount).not.toHaveBeenCalled();
  });
});
