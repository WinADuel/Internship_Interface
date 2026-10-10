import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApplication, fakeContact, fakeEmailStatus, fakeSuggestion } from "../../testing/fixtures";

vi.mock("../../api/contacts", () => ({
  getNeedsAttention: vi.fn(),
  snoozeContact: vi.fn(),
  archiveContact: vi.fn(),
  applyContactAction: vi.fn(),
  undoContactAction: vi.fn(),
  getContactHistory: vi.fn().mockResolvedValue([]),
  updateContact: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));
vi.mock("../../api/email", () => ({ getEmailStatus: vi.fn(), acceptSuggestion: vi.fn(), dismissSuggestion: vi.fn() }));
vi.mock("../../api/applications", () => ({ getApplication: vi.fn() }));

import {
  applyContactAction,
  archiveContact,
  getNeedsAttention,
  snoozeContact,
  undoContactAction,
} from "../../api/contacts";
import { getApplication } from "../../api/applications";
import { acceptSuggestion, dismissSuggestion, getEmailStatus } from "../../api/email";
import { emailStatus } from "../../stores/email";
import { showToast } from "../../stores/toast";
import { undoDeadlines } from "../../stores/contacts";
import SuggestionCard from "../email/SuggestionCard.svelte";
import NeedsAttention from "./NeedsAttention.svelte";

beforeEach(() => {
  vi.mocked(getNeedsAttention).mockReset();
  vi.mocked(snoozeContact).mockReset().mockResolvedValue(fakeContact());
  vi.mocked(archiveContact).mockReset().mockResolvedValue(fakeContact({ archived: true }));
  vi.mocked(applyContactAction).mockReset().mockResolvedValue(fakeContact());
  vi.mocked(undoContactAction).mockReset();
  vi.mocked(showToast).mockReset();
  undoDeadlines.set({});
  emailStatus.set(null);
  vi.mocked(getEmailStatus).mockReset().mockResolvedValue(fakeEmailStatus());
});

describe("NeedsAttention", () => {
  it("links to the email updates waiting for review", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([]);
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 3 }));
    render(NeedsAttention);
    const link = await screen.findByRole("link", { name: "3 email updates to review" });
    expect(link.getAttribute("href")).toBe("#/email");
    expect(screen.queryByText("Nothing needs attention.")).toBeNull();
    emailStatus.set(fakeEmailStatus({ pendingCount: 1 }));
    expect(await screen.findByRole("link", { name: "1 email update to review" })).toBeInTheDocument();
  });

  it.each([
    ["Accept", () => vi.mocked(acceptSuggestion).mockResolvedValue(fakeSuggestion({ state: "accepted" }))],
    ["Dismiss", () => vi.mocked(dismissSuggestion).mockResolvedValue(fakeSuggestion({ state: "dismissed" }))],
  ])("the email row goes down after %s on an email card", async (button, decide) => {
    decide();
    vi.mocked(getNeedsAttention).mockResolvedValue([]);
    vi.mocked(getApplication).mockResolvedValue(fakeApplication({ id: 1 }));
    vi.mocked(getEmailStatus).mockResolvedValueOnce(fakeEmailStatus({ pendingCount: 2 }));
    render(NeedsAttention);
    await screen.findByRole("link", { name: "2 email updates to review" });
    render(SuggestionCard, { suggestion: fakeSuggestion() });
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 1 }));
    await fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByRole("link", { name: "1 email update to review" })).toBeInTheDocument();
  });

  it("shows no email row when nothing is pending", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([]);
    render(NeedsAttention);
    expect(await screen.findByText("Nothing needs attention.")).toBeInTheDocument();
    expect(getEmailStatus).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: /email update/ })).toBeNull();
  });

  it("offers No response and Wait longer for gone-quiet contacts", async () => {
    vi.mocked(getNeedsAttention)
      .mockResolvedValueOnce([fakeContact({ id: 7, status: "followed_up", nudge: "gone_quiet" })])
      .mockResolvedValueOnce([]);
    render(NeedsAttention);
    expect(await screen.findByText("Gone quiet — close it out?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No response" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Wait longer" }));
    expect(snoozeContact).toHaveBeenCalledWith(7, 7);
    expect(await screen.findByText("Nothing needs attention.")).toBeInTheDocument();
    expect(getNeedsAttention).toHaveBeenCalledTimes(2);
  });

  it("unsent offers Sent, Not yet and Skip", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([fakeContact({ id: 2, draftBody: "Hi", nudge: "unsent" })]);
    render(NeedsAttention);
    await screen.findByText("Did you send this?");
    expect(screen.getByRole("button", { name: "Sent" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Not yet" }));
    expect(snoozeContact).toHaveBeenCalledWith(2, 3);
    await fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(archiveContact).toHaveBeenCalledWith(2);
  });

  it("meeting outcome offers Accepted, Declined and Still talking", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([fakeContact({ id: 3, status: "meeting", nudge: "meeting_outcome" })]);
    render(NeedsAttention);
    await screen.findByText("How did it go?");
    await fireEvent.click(screen.getByRole("button", { name: "Accepted" }));
    expect(applyContactAction).toHaveBeenCalledWith(3, "accepted", undefined);
    await fireEvent.click(screen.getByRole("button", { name: "Still talking" }));
    expect(snoozeContact).toHaveBeenCalledWith(3, 7);
  });

  it("follow-up due opens the detail panel", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([
      fakeContact({ id: 4, status: "sent", nudge: "followup_due", followupBody: "Following up" }),
    ]);
    render(NeedsAttention);
    await fireEvent.click(await screen.findByRole("button", { name: "Open follow-up" }));
    expect(screen.getByLabelText("Contact details")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Follow-up draft" })).toBeInTheDocument();
  });

  it("keeps an Undo row after a widget button clears the nudge, and Undo reverts it", async () => {
    vi.mocked(getNeedsAttention)
      .mockResolvedValueOnce([fakeContact({ id: 7, name: "Jane", status: "followed_up", nudge: "gone_quiet" })])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([fakeContact({ id: 7, name: "Jane", status: "followed_up", nudge: "gone_quiet" })]);
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ id: 7, name: "Jane", status: "declined", closedReason: "no_response" }));
    vi.mocked(undoContactAction).mockResolvedValue(fakeContact({ id: 7, name: "Jane", status: "followed_up" }));
    render(NeedsAttention);
    await fireEvent.click(await screen.findByRole("button", { name: "No response" }));
    expect(applyContactAction).toHaveBeenCalledWith(7, "no_response", undefined);
    const row = await screen.findByRole("group", { name: /Jane: marked/ });
    const undo = within(row).getByRole("button", { name: "Undo" });
    await fireEvent.click(undo);
    await vi.waitFor(() => expect(undoContactAction).toHaveBeenCalledWith(7));
    expect(await screen.findByRole("button", { name: "No response" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("Followed up applies the action", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([fakeContact({ id: 4, status: "sent", nudge: "followup_due" })]);
    render(NeedsAttention);
    await fireEvent.click(await screen.findByRole("button", { name: "Followed up" }));
    expect(applyContactAction).toHaveBeenCalledWith(4, "followed_up", undefined);
  });

  it("names each row's buttons by contact", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([
      fakeContact({ id: 8, name: "Ada", status: "replied", nudge: "replied_stale" }),
    ]);
    render(NeedsAttention);
    const row = await screen.findByRole("group", { name: "Ada" });
    expect(row).toBeInTheDocument();
    // replied_stale shows the regular status buttons.
    expect(screen.getByRole("button", { name: "Meeting set" })).toBeInTheDocument();
  });

  it("the follow-up panel lives outside the widget, closes on Escape and returns focus", async () => {
    vi.mocked(getNeedsAttention).mockResolvedValue([
      fakeContact({ id: 4, status: "sent", nudge: "followup_due", followupBody: "Following up" }),
    ]);
    const { container } = render(NeedsAttention);
    const opener = await screen.findByRole("button", { name: "Open follow-up" });
    await fireEvent.click(opener);
    const panel = screen.getByLabelText("Contact details");
    expect(container.contains(panel)).toBe(false);
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" })));
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByLabelText("Contact details")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("a failed load says so instead of showing the empty state", async () => {
    vi.mocked(getNeedsAttention).mockRejectedValue(new Error("offline"));
    render(NeedsAttention);
    expect(await screen.findByText("Couldn't load contacts needing attention.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing needs attention.")).toBeNull();
    expect(showToast).toHaveBeenCalled();
  });

  it("still offers Undo when the acted-on contact stays listed with a new nudge", async () => {
    vi.mocked(getNeedsAttention)
      .mockResolvedValueOnce([fakeContact({ id: 3, name: "Kim", status: "meeting", nudge: "meeting_outcome" })])
      .mockResolvedValue([fakeContact({ id: 3, name: "Kim", status: "sent", nudge: "followup_due" })]);
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ id: 3, name: "Kim", status: "accepted" }));
    render(NeedsAttention);
    await fireEvent.click(await screen.findByRole("button", { name: "Accepted" }));
    await screen.findByRole("button", { name: "Open follow-up" });
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });
});
