import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";

vi.mock("../../api/contacts", () => ({
  applyContactAction: vi.fn(),
  undoContactAction: vi.fn(),
  updateContact: vi.fn(),
  archiveContact: vi.fn(),
  getContactHistory: vi.fn(),
}));

import { getContactHistory } from "../../api/contacts";
import ContactDetailPanel from "./ContactDetailPanel.svelte";

beforeEach(() => {
  vi.mocked(getContactHistory).mockReset().mockResolvedValue([]);
});

describe("ContactDetailPanel", () => {
  it("renders hostile research text inertly", () => {
    const { container } = render(ContactDetailPanel, {
      contact: fakeContact({ researchSummary: '<img src=x onerror="alert(1)">', recentWork: "<script>alert(1)</script>" }),
    });
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("links only http(s) sources and URLs", () => {
    const { container } = render(ContactDetailPanel, {
      contact: fakeContact({
        websiteUrl: "javascript:alert(1)",
        sources: [
          { label: "evil", url: "javascript:alert(1)" },
          { label: "Faculty page", url: "https://cs.stanford.edu/~jlee" },
        ],
      }),
    });
    const anchors = Array.from(container.querySelectorAll("a"));
    expect(anchors.map((a) => a.getAttribute("href"))).toEqual(["https://cs.stanford.edu/~jlee"]);
    expect(anchors[0].getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.queryByText("evil")).toBeNull();
  });

  it("shows the follow-up editor only once the email is sent", () => {
    const { unmount } = render(ContactDetailPanel, { contact: fakeContact() });
    expect(screen.queryByRole("region", { name: "Follow-up draft" })).toBeNull();
    unmount();
    render(ContactDetailPanel, { contact: fakeContact({ status: "sent" }) });
    expect(screen.getByRole("region", { name: "Follow-up draft" })).toBeInTheDocument();
  });

  it("loads the status history", async () => {
    vi.mocked(getContactHistory).mockResolvedValue([
      { oldStatus: "to_contact", newStatus: "sent", changedAt: "2026-10-01T09:00:00Z" },
    ]);
    render(ContactDetailPanel, { contact: fakeContact({ id: 3, status: "sent" }) });
    expect(await screen.findByText(/To contact → Sent/)).toBeInTheDocument();
    expect(getContactHistory).toHaveBeenCalledWith(3);
  });
});
