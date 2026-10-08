import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api/discovery", () => ({
  POSTINGS_PAGE_SIZE: 50,
  listPostings: vi.fn(),
  savePosting: vi.fn(),
  dismissPosting: vi.fn(),
  restorePosting: vi.fn(),
  applyToPosting: vi.fn(),
  dismissAllPostings: vi.fn(),
  previewPaste: vi.fn(),
  confirmPaste: vi.fn(),
  startScan: vi.fn(),
  getScanStatus: vi.fn(),
}));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import { confirmPaste, getScanStatus, listPostings, previewPaste } from "../lib/api/discovery";
import { discoveryStatus } from "../lib/stores/discovery";
import { fakePosting, fakeScanStatus } from "../lib/testing/fixtures";
import type { PostingView } from "../lib/types/discovery";
import Discover from "./Discover.svelte";

const BY_VIEW: Record<PostingView, string> = { inbox: "Stripe", saved: "Figma", dismissed: "Notion" };

beforeEach(() => {
  discoveryStatus.set(null);
  vi.mocked(listPostings)
    .mockReset()
    .mockImplementation(async (view = "inbox") => ({ items: [fakePosting({ company: BY_VIEW[view] })], total: 1 }));
  vi.mocked(getScanStatus).mockReset().mockResolvedValue(fakeScanStatus());
  vi.mocked(previewPaste).mockReset();
  vi.mocked(confirmPaste).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Discover page", () => {
  it("has Inbox, Saved, Dismissed and Watchlist tabs with Inbox open", async () => {
    render(Discover);
    const tablist = screen.getByRole("tablist", { name: "Postings" });
    const tabs = screen.getAllByRole("tab");
    expect(tablist).toContainElement(tabs[0]);
    expect(tabs.map((t) => t.textContent?.trim())).toEqual(["Inbox", "Saved", "Dismissed", "Watchlist"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: "Inbox" })).toBeInTheDocument();
    expect(await screen.findByText("Stripe")).toBeInTheDocument();
    expect(listPostings).toHaveBeenCalledWith("inbox", { offset: 0 });
  });

  it("switches lists when a tab is clicked", async () => {
    render(Discover);
    await screen.findByText("Stripe");
    await fireEvent.click(screen.getByRole("tab", { name: "Saved" }));
    expect(screen.getByRole("tab", { name: "Saved" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Figma")).toBeInTheDocument();
    expect(screen.queryByText("Stripe")).toBeNull();
    await fireEvent.click(screen.getByRole("tab", { name: "Dismissed" }));
    expect(await screen.findByText("Notion")).toBeInTheDocument();
  });

  it("moves between tabs with the arrow, Home and End keys", async () => {
    render(Discover);
    const inbox = screen.getByRole("tab", { name: "Inbox" });
    expect(inbox).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Saved" })).toHaveAttribute("tabindex", "-1");
    await fireEvent.keyDown(inbox, { key: "ArrowRight" });
    const saved = screen.getByRole("tab", { name: "Saved" });
    expect(saved).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(saved);
    await fireEvent.keyDown(saved, { key: "ArrowLeft" });
    await fireEvent.keyDown(screen.getByRole("tab", { name: "Inbox" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Watchlist" })).toHaveAttribute("aria-selected", "true");
    await fireEvent.keyDown(screen.getByRole("tab", { name: "Watchlist" }), { key: "Home" });
    expect(screen.getByRole("tab", { name: "Inbox" })).toHaveAttribute("aria-selected", "true");
    await fireEvent.keyDown(screen.getByRole("tab", { name: "Inbox" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "Watchlist" })).toHaveAttribute("aria-selected", "true");
  });

  it("has a Watchlist tab panel", async () => {
    render(Discover);
    await fireEvent.click(screen.getByRole("tab", { name: "Watchlist" }));
    expect(screen.getByRole("tabpanel", { name: "Watchlist" })).toBeInTheDocument();
  });

  it("a pasted posting opens the Saved tab, freshly loaded", async () => {
    vi.mocked(previewPaste).mockResolvedValue({
      company: "Figma", title: "SWE Intern", locations: [], url: "https://figma.com/j/1", datePosted: null,
      source: "pasted",
    });
    vi.mocked(confirmPaste).mockResolvedValue(fakePosting({ id: 8, company: "Figma", state: "saved" }));
    render(Discover);
    await screen.findByText("Stripe");
    await fireEvent.input(screen.getByLabelText("Posting link"), { target: { value: "https://figma.com/j/1" } });
    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Save to Saved" }));
    await vi.waitFor(() => expect(screen.getByRole("tab", { name: "Saved" })).toHaveAttribute("aria-selected", "true"));
    await vi.waitFor(() => expect(listPostings).toHaveBeenLastCalledWith("saved", { offset: 0 }));
  });

  it("reloads the open list when a running scan finishes", async () => {
    vi.useFakeTimers();
    vi.mocked(getScanStatus)
      .mockResolvedValueOnce(fakeScanStatus({ scanning: true }))
      .mockResolvedValue(fakeScanStatus({ lastScanAt: "2026-10-08T10:00:00Z" }));
    render(Discover);
    await vi.advanceTimersByTimeAsync(0);
    expect(listPostings).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(listPostings).toHaveBeenCalledTimes(2);
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0 });
  });
});
