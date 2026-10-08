import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";
import { undoDeadlines } from "../../stores/contacts";
import type { ContactStatus } from "../../types/contact";

vi.mock("../../api/contacts", () => ({
  applyContactAction: vi.fn(),
  undoContactAction: vi.fn(),
}));

import { applyContactAction, undoContactAction } from "../../api/contacts";
import ContactStatusButtons from "./ContactStatusButtons.svelte";

const EXPECTED: Array<[ContactStatus, string[]]> = [
  ["to_contact", ["Sent"]],
  ["sent", ["Followed up", "Replied", "Declined"]],
  ["followed_up", ["Replied", "Declined", "No response"]],
  ["replied", ["Meeting set", "Accepted", "Declined"]],
  ["meeting", ["Accepted", "Declined"]],
  ["accepted", []],
  ["declined", []],
];

const ACTION_NAMES = /^(Sent|Followed up|Replied|Declined|No response|Meeting set|Accepted)$/;

beforeEach(() => {
  vi.mocked(applyContactAction).mockReset();
  vi.mocked(undoContactAction).mockReset();
  undoDeadlines.set({});
});
afterEach(() => vi.useRealTimers());

describe("ContactStatusButtons", () => {
  it.each(EXPECTED)("renders the spec buttons for %s", (status, labels) => {
    render(ContactStatusButtons, { contact: fakeContact({ status }) });
    const names = screen.queryAllByRole("button", { name: ACTION_NAMES }).map((b) => b.textContent);
    expect(names).toEqual(labels);
  });

  it("clicking Sent applies the action", async () => {
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ id: 4, status: "sent" }));
    render(ContactStatusButtons, { contact: fakeContact({ id: 4 }) });
    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    expect(applyContactAction).toHaveBeenCalledWith(4, "sent", { on: undefined, meetingAt: undefined });
  });

  it("sends the backdated day when one is picked", async () => {
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ status: "sent" }));
    render(ContactStatusButtons, { contact: fakeContact() });
    await fireEvent.click(screen.getByRole("button", { name: "It was actually on…" }));
    await fireEvent.input(screen.getByLabelText("It was actually on"), { target: { value: "2026-10-01" } });
    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    const opts = vi.mocked(applyContactAction).mock.calls[0][2];
    expect(opts?.on).toBe(new Date("2026-10-01T12:00:00").toISOString());
  });

  it("meeting set asks for a time before submitting", async () => {
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ status: "meeting" }));
    render(ContactStatusButtons, { contact: fakeContact({ status: "replied" }) });
    await fireEvent.click(screen.getByRole("button", { name: "Meeting set" }));
    expect(applyContactAction).not.toHaveBeenCalled();
    const save = screen.getByRole("button", { name: "Save meeting" });
    expect(save).toBeDisabled();
    await fireEvent.input(screen.getByLabelText("Meeting time"), { target: { value: "2026-10-09T15:00" } });
    await fireEvent.click(save);
    expect(vi.mocked(applyContactAction).mock.calls[0][2]?.meetingAt).toBe(new Date("2026-10-09T15:00").toISOString());
  });

  it("offers Undo for 60 seconds after an action", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ status: "sent" }));
    vi.mocked(undoContactAction).mockResolvedValue(fakeContact({ status: "to_contact" }));
    render(ContactStatusButtons, { contact: fakeContact() });
    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undoContactAction).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(60_001);
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });
});
