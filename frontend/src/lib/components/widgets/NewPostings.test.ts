import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakePosting } from "../../testing/fixtures";

vi.mock("../../api/discovery", () => ({ listPostings: vi.fn() }));

import { listPostings } from "../../api/discovery";
import NewPostings from "./NewPostings.svelte";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 8, 12));
  vi.mocked(listPostings).mockReset();
});

afterEach(() => vi.useRealTimers());

const five = () =>
  [1, 2, 3, 4, 5].map((id) =>
    fakePosting({ id, company: `Co${id}`, title: `Intern ${id}`, datePosted: "2026-10-05" }),
  );

describe("NewPostings", () => {
  it("asks for the top five Inbox postings by Best match", async () => {
    vi.mocked(listPostings).mockResolvedValue({ items: [], total: 0, topPicks: 0 });
    render(NewPostings);
    await screen.findByText(/No new matches/);
    expect(listPostings).toHaveBeenCalledWith("inbox", { limit: 5, sort: "best" });
  });

  it("shows the Inbox count and five rows linking to Discover", async () => {
    vi.mocked(listPostings).mockResolvedValue({ items: five(), total: 42, topPicks: 3 });
    render(NewPostings);
    const count = await screen.findByRole("link", { name: "42 new matches" });
    expect(count.getAttribute("href")).toBe("#/discover");
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    const first = screen.getByRole("link", { name: "Co1 – Intern 1" });
    expect(first.getAttribute("href")).toBe("#/discover");
    expect(rows[0].textContent).toContain("3 days ago");
  });

  it("uses the singular for one match and falls back to when it was found", async () => {
    vi.mocked(listPostings).mockResolvedValue({
      items: [fakePosting({ datePosted: null, firstSeenAt: new Date(2026, 9, 7, 9).toISOString() })],
      total: 1,
      topPicks: 0,
    });
    render(NewPostings);
    expect(await screen.findByRole("link", { name: "1 new match" })).toBeInTheDocument();
    expect(screen.getByRole("listitem").textContent).toContain("Found 1 day ago");
  });

  it("shows the empty state with a link to Settings", async () => {
    vi.mocked(listPostings).mockResolvedValue({ items: [], total: 0, topPicks: 0 });
    const { container } = render(NewPostings);
    const empty = await screen.findByText(/No new matches/);
    expect(empty.textContent).toBe("No new matches. Adjust filters in Settings.");
    expect(container.querySelector('a[href="#/settings"]')).not.toBeNull();
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("shows a failure state and retries", async () => {
    vi.mocked(listPostings)
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce({ items: five().slice(0, 2), total: 2, topPicks: 0 });
    render(NewPostings);
    expect(await screen.findByText("Couldn't load new postings.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "2 new matches" })).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load new postings.")).toBeNull();
    expect(listPostings).toHaveBeenCalledTimes(2);
  });

  it("renders untrusted titles as plain text", async () => {
    vi.mocked(listPostings).mockResolvedValue({
      items: [fakePosting({ title: "<img src=x onerror=alert(1)>" })],
      total: 1,
      topPicks: 0,
    });
    const { container } = render(NewPostings);
    expect(await screen.findByText("Stripe – <img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
