import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/email", () => ({ acceptSuggestion: vi.fn(), dismissSuggestion: vi.fn() }));
vi.mock("../../api/interviews", () => ({ createRound: vi.fn(), updateRound: vi.fn() }));
vi.mock("../../stores/email", () => ({
  afterAccept: vi.fn().mockResolvedValue(undefined),
  refreshEmailStatus: vi.fn().mockResolvedValue(null),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { acceptSuggestion, dismissSuggestion } from "../../api/email";
import { createRound } from "../../api/interviews";
import { afterAccept, refreshEmailStatus } from "../../stores/email";
import { showToast } from "../../stores/toast";
import { fakeSuggestion } from "../../testing/fixtures";
import SuggestionCard from "./SuggestionCard.svelte";

beforeEach(() => {
  vi.mocked(acceptSuggestion).mockReset();
  vi.mocked(dismissSuggestion).mockReset();
  vi.mocked(createRound).mockReset();
  vi.mocked(afterAccept).mockClear();
  vi.mocked(refreshEmailStatus).mockClear();
  vi.mocked(showToast).mockReset();
});

describe("SuggestionCard", () => {
  it("shows sender, subject, snippet, date, the match and the suggested action", () => {
    render(SuggestionCard, { suggestion: fakeSuggestion() });
    const card = screen.getByRole("article", { name: "Thank you for applying to Acme" });
    expect(card).toHaveTextContent("Application received");
    expect(card).toHaveTextContent("From Acme Recruiting <jobs@acme.com>");
    expect(card).toHaveTextContent("We received your application for SWE Intern.");
    expect(card).toHaveTextContent("Matched: Acme — SWE Intern");
    expect(card).toHaveTextContent("Suggested: Mark applied");
    expect(card.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-08T15:00:00Z");
    const gmail = screen.getByRole("link", { name: "Open in Gmail" });
    expect(gmail.getAttribute("href")).toBe("https://mail.google.com/mail/u/0/#all/thread-1");
    expect(gmail.getAttribute("target")).toBe("_blank");
    expect(gmail.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders email text as text, never as markup", () => {
    const { container } = render(SuggestionCard, {
      suggestion: fakeSuggestion({
        subject: "<img src=x onerror=alert(1)>",
        snippet: "<b>bold</b> <script>x()</script>",
        fromName: "<i>Evil</i>",
      }),
    });
    expect(container.querySelector("img, b, script, i")).toBeNull();
    expect(container).toHaveTextContent("<b>bold</b> <script>x()</script>");
    expect(container).toHaveTextContent("<img src=x onerror=alert(1)>");
  });

  it("hides Open in Gmail for a link that isn't https://mail.google.com", () => {
    render(SuggestionCard, { suggestion: fakeSuggestion({ gmailUrl: "javascript:alert(1)" }) });
    expect(screen.queryByRole("link", { name: "Open in Gmail" })).toBeNull();
  });

  it("Accept applies it and reports the decided suggestion", async () => {
    const accepted = fakeSuggestion({ state: "accepted", decidedAt: "2026-10-09T10:00:00Z" });
    vi.mocked(acceptSuggestion).mockResolvedValue(accepted);
    const onchanged = vi.fn();
    render(SuggestionCard, { suggestion: fakeSuggestion(), onchanged });
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(acceptSuggestion).toHaveBeenCalledWith(1, {});
    await vi.waitFor(() => expect(onchanged).toHaveBeenCalledWith(accepted));
    expect(afterAccept).toHaveBeenCalledWith(accepted);
    expect(showToast).toHaveBeenCalledWith("Accepted: Mark applied.", "info");
  });

  it("Dismiss dismisses and refreshes the count", async () => {
    const dismissed = fakeSuggestion({ state: "dismissed" });
    vi.mocked(dismissSuggestion).mockResolvedValue(dismissed);
    const onchanged = vi.fn();
    render(SuggestionCard, { suggestion: fakeSuggestion({ id: 4 }), onchanged });
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await vi.waitFor(() => expect(onchanged).toHaveBeenCalledWith(dismissed));
    expect(dismissSuggestion).toHaveBeenCalledWith(4);
    expect(refreshEmailStatus).toHaveBeenCalled();
    expect(afterAccept).not.toHaveBeenCalled();
  });

  it("a stale suggestion says so and asks for a reload", async () => {
    vi.mocked(acceptSuggestion).mockRejectedValue(new ApiError(409, "this suggestion no longer applies"));
    const onchanged = vi.fn();
    render(SuggestionCard, { suggestion: fakeSuggestion(), onchanged });
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await vi.waitFor(() => expect(onchanged).toHaveBeenCalledWith(null));
    expect(showToast).toHaveBeenCalledWith("Couldn't accept: this suggestion no longer applies");
    expect(refreshEmailStatus).toHaveBeenCalled();
  });

  it("another failure keeps the card and doesn't reload", async () => {
    vi.mocked(acceptSuggestion).mockRejectedValue(new ApiError(500, "boom"));
    const onchanged = vi.fn();
    render(SuggestionCard, { suggestion: fakeSuggestion(), onchanged });
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't accept: boom"));
    expect(onchanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Accept" })).not.toBeDisabled();
  });

  it("an interview opens the add-round form with the suggested kind and accepts with the round", async () => {
    vi.mocked(acceptSuggestion).mockResolvedValue(fakeSuggestion({ kind: "interview", state: "accepted" }));
    const onchanged = vi.fn();
    render(SuggestionCard, {
      suggestion: fakeSuggestion({ kind: "interview", roundKind: "technical", applicationId: 3 }),
      onchanged,
    });
    expect(screen.getByText("Suggested: Add an interview round")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    const form = screen.getByRole("form", { name: "New round" });
    expect(within(form).queryByLabelText("Application")).toBeNull(); // the round goes to this application
    expect((within(form).getByLabelText("Kind") as HTMLSelectElement).value).toBe("technical");
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    await fireEvent.input(within(form).getByLabelText("Title"), { target: { value: "Coding round" } });
    await fireEvent.input(within(form).getByLabelText("Duration (minutes)"), { target: { value: "45" } });
    await fireEvent.click(within(form).getByRole("button", { name: "Accept and add round" }));
    await vi.waitFor(() => expect(onchanged).toHaveBeenCalled());
    expect(acceptSuggestion).toHaveBeenCalledWith(1, {
      round: {
        kind: "technical",
        title: "Coding round",
        scheduledAt: null,
        durationMinutes: 45,
        format: null,
        location: null,
        interviewers: null,
      },
    });
    expect(createRound).not.toHaveBeenCalled();
    expect(screen.queryByRole("form", { name: "New round" })).toBeNull();
  });

  it("an interview's round form can be cancelled", async () => {
    render(SuggestionCard, { suggestion: fakeSuggestion({ kind: "interview", roundKind: null }) });
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect((screen.getByLabelText("Kind") as HTMLSelectElement).value).toBe("other");
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form", { name: "New round" })).toBeNull();
    expect(acceptSuggestion).not.toHaveBeenCalled();
  });

  it("a new application lets you edit the company and role before adding it", async () => {
    vi.mocked(acceptSuggestion).mockResolvedValue(fakeSuggestion({ kind: "new_application", state: "accepted" }));
    const suggestion = fakeSuggestion({
      kind: "new_application",
      application: null,
      applicationId: null,
      proposedCompany: "Rivian",
      proposedRole: null,
      fromName: "Rivian Careers",
      fromEmail: "no-reply@greenhouse.io",
    });
    render(SuggestionCard, { suggestion });
    expect(screen.getByText("Matched: Rivian")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    const form = screen.getByRole("form", { name: "New application from email" });
    expect((within(form).getByLabelText("Company") as HTMLInputElement).value).toBe("Rivian");
    await fireEvent.submit(form);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter the company and the role.");
    expect(acceptSuggestion).not.toHaveBeenCalled();
    await fireEvent.input(within(form).getByLabelText("Company"), { target: { value: " Rivian Automotive " } });
    await fireEvent.input(within(form).getByLabelText("Role"), { target: { value: "Software Intern" } });
    await fireEvent.click(within(form).getByRole("button", { name: "Add to tracker" }));
    expect(acceptSuggestion).toHaveBeenCalledWith(1, { company: "Rivian Automotive", roleTitle: "Software Intern" });
  });

  it("a decided suggestion shows its outcome and no Accept or Dismiss", () => {
    render(SuggestionCard, {
      suggestion: fakeSuggestion({ state: "auto_applied", decidedAt: "2026-10-09T10:00:00Z" }),
    });
    expect(screen.getAllByText(/Applied automatically/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open in Gmail" })).toBeInTheDocument();
  });

  it("compact leaves out the application it is already shown under, but keeps a contact", () => {
    const { unmount } = render(SuggestionCard, { suggestion: fakeSuggestion(), compact: true });
    expect(screen.queryByText(/Matched:/)).toBeNull();
    unmount();
    render(SuggestionCard, {
      suggestion: fakeSuggestion({
        kind: "contact_reply",
        contactId: 5,
        contact: { id: 5, name: "Dana Lee", organization: "Acme", status: "sent" },
      }),
      compact: true,
    });
    expect(screen.getByText("Matched: Dana Lee, Acme")).toBeInTheDocument();
  });
});
