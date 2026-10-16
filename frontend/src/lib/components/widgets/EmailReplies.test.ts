import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeSuggestion } from "../../testing/fixtures";
import type { EmailHighlights, EmailSuggestion, HighlightList } from "../../types/email";

vi.mock("../../api/email", () => ({ getEmailHighlights: vi.fn() }));

import { getEmailHighlights } from "../../api/email";
import EmailReplies from "./EmailReplies.svelte";

const at = (day: number) => new Date(2026, 9, day, 12).toISOString();
const list = (items: EmailSuggestion[], count = items.length): HighlightList => ({ count, items });

function highlights(tabs: Partial<EmailHighlights["tabs"]> = {}, gmailGranted = true): EmailHighlights {
  return {
    gmailGranted,
    tabs: { replies: list([]), interview: list([]), offer: list([]), rejection: list([]), ...tabs },
  };
}

const reply = fakeSuggestion({
  id: 11,
  kind: "contact_reply",
  state: "auto_applied",
  receivedAt: at(14),
  fromName: "Dana Lee",
  fromEmail: "dana@mit.edu",
  subject: "Re: Coffee chat?",
  snippet: "Happy to talk next week",
  applicationId: null,
  application: null,
  contactId: 5,
  contact: { id: 5, name: "Dana Lee", organization: "MIT", status: "replied" },
  gmailUrl: "https://mail.google.com/mail/u/me%40gmail.com/#all/t11",
});

const interview = fakeSuggestion({
  id: 12,
  kind: "interview",
  state: "pending",
  receivedAt: at(13),
  fromName: "",
  fromEmail: "jobs@acme.com",
  subject: "Interview with Acme",
  snippet: "Please share your availability",
});

beforeEach(() => {
  vi.mocked(getEmailHighlights).mockReset();
});

describe("EmailReplies widget", () => {
  it("asks once for the newest 8 per tab and shows each tab's count", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(
      highlights({ replies: list([reply], 3), interview: list([interview]), rejection: list([], 2) }),
    );
    render(EmailReplies);
    const tabs = await screen.findAllByRole("tab");
    expect(getEmailHighlights).toHaveBeenCalledTimes(1);
    expect(getEmailHighlights).toHaveBeenCalledWith(8);
    expect(tabs.map((t) => t.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      "Cold emails (3)",
      "Interviews (1)",
      "Offers (0)",
      "Rejections (2)",
    ]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });

  it("shows a cold email reply as one line linking to the thread in Gmail", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights({ replies: list([reply]) }));
    render(EmailReplies);
    const panel = await screen.findByRole("tabpanel");
    const row = within(panel).getByRole("link", { name: /Dana Lee/ });
    expect(row.textContent).toBe("Oct 14 Dana Lee · Dana Lee, MIT · Re: Coffee chat? — Happy to talk next week");
    expect(row.getAttribute("href")).toBe("https://mail.google.com/mail/u/me%40gmail.com/#all/t11");
    expect(row.getAttribute("target")).toBe("_blank");
    expect(row.getAttribute("rel")).toBe("noopener noreferrer");
    expect(row.getAttribute("title")).toBe(
      "Oct 14 · Dana Lee <dana@mit.edu> · Dana Lee, MIT · Re: Coffee chat? — Happy to talk next week",
    );
    expect(row.querySelector("time")?.getAttribute("datetime")).toBe(reply.receivedAt);
    // Applied automatically: nothing to review.
    expect(within(panel).queryByRole("link", { name: "To review" })).toBeNull();
  });

  it("switches tabs; application rows name the application and pending ones link to Email updates", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights({ replies: list([reply]), interview: list([interview]) }));
    render(EmailReplies);
    await fireEvent.click(await screen.findByRole("tab", { name: "Interviews (1)" }));
    expect(screen.getByRole("tab", { name: "Interviews (1)" })).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAccessibleName("Interviews (1)");
    expect(panel).not.toHaveTextContent("Dana Lee");
    const row = within(panel).getByRole("link", { name: /jobs@acme\.com/ });
    expect(row.textContent).toBe("Oct 13 jobs@acme.com · Acme — SWE Intern · Interview with Acme — Please share your availability");
    const tag = within(panel).getByRole("link", { name: "To review" });
    expect(tag.getAttribute("href")).toBe("#/email");
    expect(tag.getAttribute("aria-describedby")).toBe(row.id); // which email it reviews
  });

  it("moves between tabs with the arrow keys", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights());
    render(EmailReplies);
    const first = await screen.findByRole("tab", { name: "Cold emails (0)" });
    await fireEvent.keyDown(first, { key: "ArrowLeft" });
    const last = screen.getByRole("tab", { name: "Rejections (0)" });
    expect(last).toHaveAttribute("aria-selected", "true");
    await vi.waitFor(() => expect(document.activeElement).toBe(last));
    expect(screen.getByText("No rejection emails yet.")).toBeInTheDocument();
  });

  it("shows each tab's empty message and the See all link", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights());
    render(EmailReplies);
    expect(await screen.findByText("No cold email replies yet.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("tab", { name: "Offers (0)" }));
    expect(screen.getByText("No offer emails yet.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("tab", { name: "Interviews (0)" }));
    expect(screen.getByText("No interview emails yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all in Email updates" }).getAttribute("href")).toBe("#/email");
  });

  it("renders email text as text and never links outside Gmail", async () => {
    const evil = fakeSuggestion({
      id: 13,
      kind: "rejection",
      fromName: "<i>Evil</i>",
      subject: "<img src=x onerror=alert(1)>",
      snippet: "<script>x()</script>",
      gmailUrl: "javascript:alert(1)",
    });
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights({ rejection: list([evil]) }));
    const { container } = render(EmailReplies);
    await fireEvent.click(await screen.findByRole("tab", { name: "Rejections (1)" }));
    const panel = screen.getByRole("tabpanel");
    expect(container.querySelector("img, script, i")).toBeNull();
    expect(panel).toHaveTextContent("<img src=x onerror=alert(1)> — <script>x()</script>");
    expect(within(panel).queryByRole("link", { name: /Evil/ })).toBeNull();
    expect(within(panel).getByText("<i>Evil</i>").closest(".row")?.getAttribute("title")).toContain("<i>Evil</i>");
  });

  it("says (no subject) and leaves out a missing preview", async () => {
    const bare = fakeSuggestion({ id: 14, kind: "offer", state: "accepted", subject: "", snippet: "", receivedAt: at(2) });
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights({ offer: list([bare]) }));
    render(EmailReplies);
    await fireEvent.click(await screen.findByRole("tab", { name: "Offers (1)" }));
    const row = screen.getByRole("link", { name: /Acme Recruiting/ });
    expect(row.textContent).toBe("Oct 2 Acme Recruiting · Acme — SWE Intern · (no subject)");
  });

  it("asks to connect Gmail when no inbox is connected", async () => {
    vi.mocked(getEmailHighlights).mockResolvedValue(highlights({}, false));
    render(EmailReplies);
    const link = await screen.findByRole("link", { name: "Connect Gmail in Settings" });
    expect(link.getAttribute("href")).toBe("#/settings");
    expect(link.parentElement).toHaveTextContent("Connect Gmail in Settings to see replies here.");
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("shows Loading, then a failure with Retry", async () => {
    let fail!: (e: Error) => void;
    vi.mocked(getEmailHighlights)
      .mockReturnValueOnce(new Promise((_, reject) => (fail = reject)))
      .mockResolvedValueOnce(highlights({ replies: list([reply]) }));
    render(EmailReplies);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    fail(new Error("down"));
    expect(await screen.findByText("Couldn't load email replies.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: /Dana Lee/ })).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load email replies.")).toBeNull();
    expect(getEmailHighlights).toHaveBeenCalledTimes(2);
  });
});
