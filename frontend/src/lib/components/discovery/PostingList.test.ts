import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({
  POSTINGS_PAGE_SIZE: 50,
  listPostings: vi.fn(),
  savePosting: vi.fn(),
  dismissPosting: vi.fn(),
  restorePosting: vi.fn(),
  applyToPosting: vi.fn(),
  dismissAllPostings: vi.fn(),
}));
vi.mock("../../stores/discovery", () => ({ refreshDiscoveryStatus: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import {
  applyToPosting,
  dismissAllPostings,
  dismissPosting,
  listPostings,
  restorePosting,
  savePosting,
} from "../../api/discovery";
import { applications } from "../../stores/applications";
import { refreshDiscoveryStatus } from "../../stores/discovery";
import { showToast } from "../../stores/toast";
import { fakeApplication, fakePosting } from "../../testing/fixtures";
import type { Posting } from "../../types/discovery";
import PostingList from "./PostingList.svelte";

const stripe = fakePosting({ id: 1, company: "Stripe", title: "SWE Intern" });
const figma = fakePosting({ id: 2, company: "Figma", title: "Data Intern", url: "https://figma.com/jobs/2" });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
  return { promise, resolve, reject };
}

function page(items: Posting[], total = items.length, topPicks: number | null = null) {
  return { items, total, topPicks };
}

function rowNames(): string[] {
  return screen.queryAllByRole("listitem").map((li) => li.querySelector(".company")?.textContent ?? "");
}

let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.mocked(listPostings).mockReset().mockResolvedValue(page([stripe, figma]));
  vi.mocked(savePosting).mockReset();
  vi.mocked(dismissPosting).mockReset();
  vi.mocked(restorePosting).mockReset();
  vi.mocked(applyToPosting).mockReset();
  vi.mocked(dismissAllPostings).mockReset();
  vi.mocked(refreshDiscoveryStatus).mockReset().mockResolvedValue(null);
  vi.mocked(showToast).mockReset();
  applications.set([]);
  confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  confirmSpy.mockRestore();
});

describe("PostingList — Inbox", () => {
  it("loads the first page of the view", async () => {
    render(PostingList, { view: "inbox" });
    await screen.findByText("Figma");
    expect(listPostings).toHaveBeenCalledWith("inbox", { offset: 0, sort: "best" });
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
  });

  it("Save removes the row at once and refreshes the Inbox count", async () => {
    const pending = deferred<Posting>();
    vi.mocked(savePosting).mockReturnValue(pending.promise);
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Save Stripe – SWE Intern" }));
    expect(savePosting).toHaveBeenCalledWith(1);
    expect(rowNames()).toEqual(["Figma"]);
    pending.resolve({ ...stripe, state: "saved" });
    await vi.waitFor(() => expect(refreshDiscoveryStatus).toHaveBeenCalled());
    expect(rowNames()).toEqual(["Figma"]);
    expect(showToast).not.toHaveBeenCalled();
  });

  it("puts the row back in place and shows an error when Save fails", async () => {
    vi.mocked(savePosting).mockRejectedValue(new ApiError(409, "posting is already saved"));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Save Stripe – SWE Intern" }));
    await vi.waitFor(() => expect(rowNames()).toEqual(["Stripe", "Figma"]));
    expect(showToast).toHaveBeenCalledWith("Couldn't save Stripe – SWE Intern: posting is already saved");
  });

  it("Dismiss removes the row and rolls back on a network failure", async () => {
    vi.mocked(dismissPosting).mockRejectedValue(new TypeError("Failed to fetch"));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss Figma – Data Intern" }));
    expect(dismissPosting).toHaveBeenCalledWith(2);
    await vi.waitFor(() => expect(rowNames()).toEqual(["Stripe", "Figma"]));
    expect(showToast).toHaveBeenCalledWith("Couldn't dismiss Figma – Data Intern.");
  });

  it("Dismiss all shown asks first and does nothing when cancelled", async () => {
    confirmSpy.mockReturnValue(false);
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    expect(confirmSpy).toHaveBeenCalledWith("Dismiss all 2 postings shown?");
    expect(dismissAllPostings).not.toHaveBeenCalled();
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
  });

  it("Dismiss all shown sends the ids shown, then reloads the Inbox", async () => {
    vi.mocked(dismissAllPostings).mockResolvedValue(2);
    vi.mocked(listPostings).mockResolvedValueOnce(page([stripe, figma])).mockResolvedValue(page([]));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    expect(dismissAllPostings).toHaveBeenCalledWith([1, 2]);
    await vi.waitFor(() => expect(listPostings).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("No new postings match your filters.")).toBeInTheDocument();
    expect(refreshDiscoveryStatus).toHaveBeenCalled();
  });

  it("Dismiss all shown says posting for a single row", async () => {
    confirmSpy.mockReturnValue(false);
    vi.mocked(listPostings).mockResolvedValue(page([stripe]));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    expect(confirmSpy).toHaveBeenCalledWith("Dismiss all 1 posting shown?");
  });

  it("Dismiss all shown restores the rows when it fails", async () => {
    vi.mocked(dismissAllPostings).mockRejectedValue(new ApiError(500, "boom"));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't dismiss the postings: boom"));
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
  });

  it("Dismiss all shown sends more than 500 ids in chunks of 500, one after another", async () => {
    const many = Array.from({ length: 550 }, (_, i) => fakePosting({ id: i + 1, company: `Co ${i + 1}` }));
    const first = deferred<number>();
    vi.mocked(dismissAllPostings).mockReturnValueOnce(first.promise).mockResolvedValueOnce(50);
    vi.mocked(listPostings).mockResolvedValueOnce(page(many)).mockResolvedValue(page([]));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    expect(confirmSpy).toHaveBeenCalledWith("Dismiss all 550 postings shown?");
    expect(dismissAllPostings).toHaveBeenCalledTimes(1);
    expect(dismissAllPostings).toHaveBeenNthCalledWith(1, many.slice(0, 500).map((p) => p.id));
    // While it runs: a busy note, not the empty state.
    expect(screen.getByText("Dismissing 550 postings…")).toBeInTheDocument();
    expect(screen.queryByText("No new postings match your filters.")).toBeNull();

    first.resolve(500);
    await vi.waitFor(() => expect(dismissAllPostings).toHaveBeenCalledTimes(2));
    expect(dismissAllPostings).toHaveBeenNthCalledWith(2, many.slice(500).map((p) => p.id));
    expect(await screen.findByText("No new postings match your filters.")).toBeInTheDocument();
    expect(listPostings).toHaveBeenCalledTimes(2);
    expect(refreshDiscoveryStatus).toHaveBeenCalled();
    expect(showToast).not.toHaveBeenCalled();
  });

  it("Dismiss all shown puts back only the chunk that failed and says how many went", async () => {
    const many = Array.from({ length: 550 }, (_, i) => fakePosting({ id: i + 1, company: `Co ${i + 1}` }));
    vi.mocked(dismissAllPostings).mockResolvedValueOnce(500).mockRejectedValueOnce(new ApiError(500, "boom"));
    vi.mocked(listPostings).mockResolvedValueOnce(page(many));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Dismiss all shown" }));
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Dismissed 500 of 550 postings. Couldn't dismiss the other 50: boom"),
    );
    expect(rowNames()).toEqual(many.slice(500).map((p) => p.company));
    expect(screen.getByText("Showing 50 of 50")).toBeInTheDocument();
    expect(refreshDiscoveryStatus).toHaveBeenCalled();
    expect(listPostings).toHaveBeenCalledTimes(1);
  });

  it("loads more 50 at a time while more remain", async () => {
    vi.mocked(listPostings).mockResolvedValueOnce(page([stripe], 2));
    render(PostingList, { view: "inbox" });
    await screen.findByText("Stripe");
    expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
    vi.mocked(listPostings).mockResolvedValueOnce(page([figma], 2));
    await fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 1, sort: "best" });
    await screen.findByText("Figma");
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("fetches the next postings when actions empty the page but more remain", async () => {
    vi.mocked(listPostings).mockResolvedValueOnce(page([stripe], 2)).mockResolvedValueOnce(page([figma], 1));
    vi.mocked(savePosting).mockResolvedValue({ ...stripe, state: "saved" });
    render(PostingList, { view: "inbox" });
    await fireEvent.click(await screen.findByRole("button", { name: "Save Stripe – SWE Intern" }));
    await screen.findByText("Figma");
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0, sort: "best" });
    expect(screen.queryByText("No new postings match your filters.")).toBeNull();
  });

  it("skips a posting the next page repeats", async () => {
    vi.mocked(listPostings).mockResolvedValueOnce(page([stripe], 3));
    render(PostingList, { view: "inbox" });
    await screen.findByText("Stripe");
    vi.mocked(listPostings).mockResolvedValueOnce(page([stripe, figma], 3));
    await fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("Figma");
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
  });

  it("shows a load failure with Retry", async () => {
    vi.mocked(listPostings).mockRejectedValueOnce(new ApiError(500, "boom"));
    render(PostingList, { view: "inbox" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load postings: boom");
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Stripe");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("PostingList — Inbox ranking", () => {
  const sortButton = (name: string) => screen.getByRole("button", { name });
  const topPicksChip = () => screen.getByRole("button", { name: /^Top picks/ });

  it("orders by Best match by default; Newest reloads newest first", async () => {
    render(PostingList, { view: "inbox" });
    await screen.findByText("Figma");
    expect(sortButton("Best match")).toHaveAttribute("aria-pressed", "true");
    expect(sortButton("Newest")).toHaveAttribute("aria-pressed", "false");
    vi.mocked(listPostings).mockResolvedValueOnce(page([figma, stripe]));
    await fireEvent.click(sortButton("Newest"));
    await vi.waitFor(() => expect(rowNames()).toEqual(["Figma", "Stripe"]));
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0, sort: "newest" });
    expect(sortButton("Newest")).toHaveAttribute("aria-pressed", "true");
    await fireEvent.click(sortButton("Newest"));
    expect(listPostings).toHaveBeenCalledTimes(2);
  });

  it("shows the Top picks count and filters to Top picks (score 70+) and back", async () => {
    vi.mocked(listPostings).mockResolvedValue(page([stripe, figma], 2, 12));
    render(PostingList, { view: "inbox" });
    await screen.findByText("Figma");
    expect(topPicksChip()).toHaveAccessibleName("Top picks 12");
    expect(topPicksChip()).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(topPicksChip());
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0, sort: "best", minScore: 70 });
    expect(topPicksChip()).toHaveAttribute("aria-pressed", "true");
    await fireEvent.click(topPicksChip());
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0, sort: "best" });
  });

  it("keeps the order and Top picks filter when loading more", async () => {
    vi.mocked(listPostings).mockResolvedValue(page([stripe], 2, 2));
    render(PostingList, { view: "inbox", sort: "newest", topPicksOnly: true });
    await screen.findByText("Stripe");
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 0, sort: "newest", minScore: 70 });
    vi.mocked(listPostings).mockResolvedValueOnce(page([figma], 2, 2));
    await fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("Figma");
    expect(listPostings).toHaveBeenLastCalledWith("inbox", { offset: 1, sort: "newest", minScore: 70 });
  });

  it("says when there are no Top picks and keeps the toolbar to turn the filter off", async () => {
    vi.mocked(listPostings).mockResolvedValue(page([], 0, 0));
    render(PostingList, { view: "inbox", topPicksOnly: true });
    expect(await screen.findByText(/No Top picks \(score 70\+\) right now/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "#/settings");
    expect(topPicksChip()).toHaveAttribute("aria-pressed", "true");
  });

  it("drops an older answer when the order changes before it arrives", async () => {
    const slow = deferred<ReturnType<typeof page>>();
    vi.mocked(listPostings).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(page([figma]));
    render(PostingList, { view: "inbox" });
    await fireEvent.click(sortButton("Newest"));
    await screen.findByText("Figma");
    slow.resolve(page([stripe]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(rowNames()).toEqual(["Figma"]);
  });

  it("counts a Top pick leaving the Inbox, and back if the server refuses", async () => {
    const pick = fakePosting({ id: 3, company: "Anthropic", title: "ML Intern", claudeScore: 90 });
    const low = fakePosting({ id: 4, company: "Initech", title: "Intern", localScore: 20 });
    vi.mocked(listPostings).mockResolvedValue(page([pick, low], 2, 5));
    render(PostingList, { view: "inbox" });
    await screen.findByText("Anthropic");
    vi.mocked(savePosting).mockResolvedValueOnce({ ...low, state: "saved" });
    await fireEvent.click(screen.getByRole("button", { name: "Save Initech – Intern" }));
    expect(topPicksChip()).toHaveAccessibleName("Top picks 5");
    const pending = deferred<Posting>();
    vi.mocked(dismissPosting).mockReturnValueOnce(pending.promise);
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss Anthropic – ML Intern" }));
    expect(topPicksChip()).toHaveAccessibleName("Top picks 4");
    pending.reject(new ApiError(500, "boom"));
    await vi.waitFor(() => expect(topPicksChip()).toHaveAccessibleName("Top picks 5"));
  });

  describe("a reload while an action is out", () => {
    const anthropic = fakePosting({ id: 3, company: "Anthropic", title: "ML Intern", claudeScore: 90 });

    it("a refused action does not put a second copy of the row back", async () => {
      vi.mocked(listPostings).mockResolvedValue(page([anthropic, stripe, figma], 3, 5));
      render(PostingList, { view: "inbox" });
      await screen.findByText("Anthropic");
      const pending = deferred<Posting>();
      vi.mocked(dismissPosting).mockReturnValueOnce(pending.promise);
      await fireEvent.click(screen.getByRole("button", { name: "Dismiss Anthropic – ML Intern" }));
      // The reload is answered before the dismissal: the server still lists it.
      await fireEvent.click(sortButton("Newest"));
      await vi.waitFor(() => expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]));
      pending.reject(new ApiError(500, "boom"));
      await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't dismiss Anthropic – ML Intern: boom"));
      expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]);
      expect(screen.getByText("Showing 3 of 3")).toBeInTheDocument();
      expect(topPicksChip()).toHaveAccessibleName("Top picks 5");
    });

    it("an action that went through drops the row the reload brought back", async () => {
      vi.mocked(listPostings).mockResolvedValue(page([anthropic, stripe, figma], 3, 5));
      render(PostingList, { view: "inbox" });
      await screen.findByText("Anthropic");
      const pending = deferred<Posting>();
      vi.mocked(dismissPosting).mockReturnValueOnce(pending.promise);
      await fireEvent.click(screen.getByRole("button", { name: "Dismiss Anthropic – ML Intern" }));
      await fireEvent.click(sortButton("Newest"));
      await vi.waitFor(() => expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]));
      pending.resolve({ ...anthropic, state: "dismissed" });
      await vi.waitFor(() => expect(rowNames()).toEqual(["Stripe", "Figma"]));
      expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
      expect(topPicksChip()).toHaveAccessibleName("Top picks 4");
      expect(listPostings).toHaveBeenCalledTimes(2);
    });

    it("a refused Dismiss all shown keeps the reload's list instead of the old one", async () => {
      vi.mocked(listPostings).mockResolvedValueOnce(page([stripe, figma], 2, 0));
      render(PostingList, { view: "inbox" });
      await screen.findByText("Figma");
      const pending = deferred<number>();
      vi.mocked(dismissAllPostings).mockReturnValueOnce(pending.promise);
      await fireEvent.click(screen.getByRole("button", { name: "Dismiss all shown" }));
      vi.mocked(listPostings).mockResolvedValueOnce(page([anthropic, stripe, figma], 3, 1));
      await fireEvent.click(sortButton("Newest"));
      await vi.waitFor(() => expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]));
      pending.reject(new ApiError(500, "boom"));
      await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't dismiss the postings: boom"));
      expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]);
      expect(screen.getByText("Showing 3 of 3")).toBeInTheDocument();
    });

    it("Dismiss all shown that went through drops its rows from the reload's list", async () => {
      vi.mocked(listPostings).mockResolvedValueOnce(page([stripe, figma], 2, 0));
      render(PostingList, { view: "inbox" });
      await screen.findByText("Figma");
      const pending = deferred<number>();
      vi.mocked(dismissAllPostings).mockReturnValueOnce(pending.promise);
      await fireEvent.click(screen.getByRole("button", { name: "Dismiss all shown" }));
      vi.mocked(listPostings).mockResolvedValueOnce(page([anthropic, stripe, figma], 3, 1));
      await fireEvent.click(sortButton("Newest"));
      await vi.waitFor(() => expect(rowNames()).toEqual(["Anthropic", "Stripe", "Figma"]));
      pending.resolve(2);
      await vi.waitFor(() => expect(rowNames()).toEqual(["Anthropic"]));
      expect(screen.getByText("Showing 1 of 1")).toBeInTheDocument();
      expect(topPicksChip()).toHaveAccessibleName("Top picks 1");
      // The reload's list is kept, not fetched a third time.
      expect(listPostings).toHaveBeenCalledTimes(2);
      expect(refreshDiscoveryStatus).toHaveBeenCalled();
    });
  });

  it("has no ranking toolbar outside the Inbox", async () => {
    render(PostingList, { view: "saved" });
    await screen.findByText("Figma");
    expect(listPostings).toHaveBeenCalledWith("saved", { offset: 0 });
    expect(screen.queryByRole("button", { name: "Best match" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Top picks/ })).toBeNull();
  });
});

describe("PostingList — Saved", () => {
  beforeEach(() => {
    vi.mocked(listPostings).mockResolvedValue(page([{ ...stripe, state: "saved" }, { ...figma, state: "saved" }]));
  });

  it("Apply confirms with the posting's name and does nothing when cancelled", async () => {
    confirmSpy.mockReturnValue(false);
    render(PostingList, { view: "saved" });
    await fireEvent.click(await screen.findByRole("button", { name: "Apply to Stripe – SWE Intern" }));
    expect(confirmSpy).toHaveBeenCalledWith("Add Stripe – SWE Intern to your tracker as Applied today?");
    expect(applyToPosting).not.toHaveBeenCalled();
    expect(rowNames()).toEqual(["Stripe", "Figma"]);
  });

  it("Apply moves the posting into Applications and says so", async () => {
    const created = fakeApplication({ id: 9, company: "Stripe", status: "applied" });
    vi.mocked(applyToPosting).mockResolvedValue(created);
    render(PostingList, { view: "saved" });
    await fireEvent.click(await screen.findByRole("button", { name: "Apply to Stripe – SWE Intern" }));
    expect(applyToPosting).toHaveBeenCalledWith(1);
    expect(rowNames()).toEqual(["Figma"]);
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Stripe – SWE Intern is now in Applications as Applied.", "info"),
    );
    expect(get(applications)).toEqual([created]);
  });

  it("Apply rolls back and shows the error on failure", async () => {
    vi.mocked(applyToPosting).mockRejectedValue(new ApiError(409, "posting is not saved"));
    render(PostingList, { view: "saved" });
    await fireEvent.click(await screen.findByRole("button", { name: "Apply to Stripe – SWE Intern" }));
    await vi.waitFor(() => expect(rowNames()).toEqual(["Stripe", "Figma"]));
    expect(showToast).toHaveBeenCalledWith("Couldn't apply to Stripe – SWE Intern: posting is not saved");
    expect(get(applications)).toEqual([]);
  });

  it("Remove dismisses the posting", async () => {
    vi.mocked(dismissPosting).mockResolvedValue({ ...figma, state: "dismissed" });
    render(PostingList, { view: "saved" });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Figma – Data Intern" }));
    expect(dismissPosting).toHaveBeenCalledWith(2);
    expect(rowNames()).toEqual(["Stripe"]);
  });

  it("has no Dismiss all button and its own empty state", async () => {
    vi.mocked(listPostings).mockResolvedValue(page([]));
    render(PostingList, { view: "saved" });
    expect(await screen.findByText(/Nothing saved yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss all shown" })).toBeNull();
  });
});

describe("PostingList — Dismissed", () => {
  it("Restore sends the posting back and rolls back on failure", async () => {
    vi.mocked(listPostings).mockResolvedValue(page([{ ...stripe, state: "dismissed" }]));
    vi.mocked(restorePosting).mockRejectedValueOnce(new ApiError(404, "posting not found"));
    render(PostingList, { view: "dismissed" });
    const list = await screen.findByRole("list");
    await fireEvent.click(within(list).getByRole("button", { name: "Restore Stripe – SWE Intern" }));
    expect(restorePosting).toHaveBeenCalledWith(1);
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Couldn't restore Stripe – SWE Intern: posting not found"),
    );
    expect(rowNames()).toEqual(["Stripe"]);

    vi.mocked(restorePosting).mockResolvedValueOnce({ ...stripe, state: "new" });
    await fireEvent.click(screen.getByRole("button", { name: "Restore Stripe – SWE Intern" }));
    await vi.waitFor(() => expect(refreshDiscoveryStatus).toHaveBeenCalled());
    expect(rowNames()).toEqual([]);
  });
});
