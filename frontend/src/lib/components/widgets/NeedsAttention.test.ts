import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";

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

import { applyContactAction, archiveContact, getNeedsAttention, snoozeContact } from "../../api/contacts";
import NeedsAttention from "./NeedsAttention.svelte";

beforeEach(() => {
  vi.mocked(getNeedsAttention).mockReset();
  vi.mocked(snoozeContact).mockReset().mockResolvedValue(fakeContact());
  vi.mocked(archiveContact).mockReset().mockResolvedValue(fakeContact({ archived: true }));
  vi.mocked(applyContactAction).mockReset().mockResolvedValue(fakeContact());
});

describe("NeedsAttention", () => {
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
});
