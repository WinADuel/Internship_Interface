import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { fakePosting } from "../../testing/fixtures";
import PostingRow from "./PostingRow.svelte";

const now = new Date(2026, 9, 8, 12, 0); // 8 Oct 2026, local

describe("PostingRow", () => {
  it("shows company, title, two locations plus a count, posted-ago and the source", () => {
    render(PostingRow, {
      posting: fakePosting({ locations: ["NYC", "Remote", "SF"], datePosted: "2026-10-05" }),
      view: "inbox",
      now,
      onaction: vi.fn(),
    });
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText("SWE Intern")).toBeInTheDocument();
    expect(screen.getByText("NYC, Remote +1 more")).toBeInTheDocument();
    expect(screen.getByText("Posted 3 days ago")).toBeInTheDocument();
    expect(screen.getByText("Simplify")).toBeInTheDocument();
  });

  it("falls back to when the posting was first found when it has no posted date", () => {
    render(PostingRow, {
      posting: fakePosting({ datePosted: null, firstSeenAt: new Date(2026, 9, 7, 9).toISOString() }),
      view: "inbox",
      now,
      onaction: vi.fn(),
    });
    expect(screen.getByText("Found 1 day ago")).toBeInTheDocument();
  });

  it("shows a sponsorship note unless it is Other", () => {
    const { unmount } = render(PostingRow, {
      posting: fakePosting({ sponsorship: "Does Not Offer Sponsorship" }),
      view: "inbox",
      onaction: vi.fn(),
    });
    expect(screen.getByText("Does Not Offer Sponsorship")).toBeInTheDocument();
    unmount();
    render(PostingRow, { posting: fakePosting({ sponsorship: "Other" }), view: "inbox", onaction: vi.fn() });
    expect(screen.queryByText("Other")).toBeNull();
  });

  it("shows a closed badge only on closed postings", () => {
    const { unmount } = render(PostingRow, { posting: fakePosting(), view: "saved", onaction: vi.fn() });
    expect(screen.queryByText("closed")).toBeNull();
    unmount();
    render(PostingRow, { posting: fakePosting({ closed: true }), view: "saved", onaction: vi.fn() });
    expect(screen.getByText("closed")).toBeInTheDocument();
  });

  it("renders markup in untrusted fields as literal text", () => {
    const evil = "<img src=x onerror=alert(1)>";
    const { container } = render(PostingRow, {
      posting: fakePosting({ title: evil, company: "<b>Evil</b>", locations: [evil], sponsorship: evil }),
      view: "inbox",
      onaction: vi.fn(),
    });
    expect(screen.getByText(evil, { selector: ".title" })).toBeInTheDocument();
    expect(screen.getByText("<b>Evil</b>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("opens http(s) links in a new tab without an opener", () => {
    render(PostingRow, { posting: fakePosting(), view: "inbox", onaction: vi.fn() });
    const link = screen.getByRole("link", { name: "Open Stripe – SWE Intern in a new tab" });
    expect(link.getAttribute("href")).toBe("https://stripe.com/jobs/1");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders no Open link for a non-web URL", () => {
    render(PostingRow, { posting: fakePosting({ url: "javascript:alert(1)" }), view: "inbox", onaction: vi.fn() });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("offers Save and Dismiss in the Inbox, labelled with the posting", async () => {
    const onaction = vi.fn();
    render(PostingRow, { posting: fakePosting(), view: "inbox", onaction });
    await fireEvent.click(screen.getByRole("button", { name: "Save Stripe – SWE Intern" }));
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss Stripe – SWE Intern" }));
    expect(onaction.mock.calls).toEqual([["save"], ["dismiss"]]);
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("offers Apply and Remove in Saved", async () => {
    const onaction = vi.fn();
    render(PostingRow, { posting: fakePosting({ state: "saved" }), view: "saved", onaction });
    await fireEvent.click(screen.getByRole("button", { name: "Apply to Stripe – SWE Intern" }));
    await fireEvent.click(screen.getByRole("button", { name: "Remove Stripe – SWE Intern" }));
    expect(onaction.mock.calls).toEqual([["apply"], ["remove"]]);
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("offers only Restore in Dismissed", async () => {
    const onaction = vi.fn();
    render(PostingRow, { posting: fakePosting({ state: "dismissed" }), view: "dismissed", onaction });
    await fireEvent.click(screen.getByRole("button", { name: "Restore Stripe – SWE Intern" }));
    expect(onaction).toHaveBeenCalledWith("restore");
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
