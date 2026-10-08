import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";

vi.mock("../../api/contacts", () => ({
  applyContactAction: vi.fn(),
  updateContact: vi.fn(),
}));

import { applyContactAction, updateContact } from "../../api/contacts";
import DraftEditor from "./DraftEditor.svelte";

let openSpy: ReturnType<typeof vi.spyOn>;
let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.mocked(applyContactAction).mockReset();
  vi.mocked(updateContact).mockReset();
  openSpy = vi.spyOn(window, "open").mockReturnValue(null);
  confirmSpy = vi.spyOn(window, "confirm");
});
afterEach(() => vi.restoreAllMocks());

const draft = { email: "jlee@stanford.edu", draftSubject: "Hello", draftBody: "Dear Prof. Lee" };

describe("DraftEditor", () => {
  it("asks before opening a guessed address and stays put when declined", async () => {
    confirmSpy.mockReturnValue(false);
    render(DraftEditor, { contact: fakeContact({ ...draft, emailConfidence: "pattern_guess" }), which: "draft" });
    await fireEvent.click(screen.getByRole("button", { name: "Open in Gmail" }));
    expect(confirmSpy).toHaveBeenCalledWith("This address is a guess and may bounce. Open anyway?");
    expect(openSpy).not.toHaveBeenCalled();
    expect(screen.queryByText("Did you send it?")).toBeNull();
  });

  it("opens a found address without asking, then offers Sent", async () => {
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ status: "sent" }));
    render(DraftEditor, { contact: fakeContact({ ...draft, id: 5, emailConfidence: "found" }), which: "draft" });
    await fireEvent.click(screen.getByRole("button", { name: "Open in Gmail" }));
    expect(confirmSpy).not.toHaveBeenCalled();
    const [url, target, features] = openSpy.mock.calls[0];
    expect(String(url).startsWith("https://mail.google.com/mail/?view=cm")).toBe(true);
    expect(String(url)).toContain("to=jlee%40stanford.edu");
    expect([target, features]).toEqual(["_blank", "noopener"]);
    expect(screen.getByText(/Did you send it\?/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    expect(applyContactAction).toHaveBeenCalledWith(5, "sent", undefined);
  });

  it("follow-up editor marks followed_up and Not yet hides the prompt", async () => {
    render(DraftEditor, {
      contact: fakeContact({ email: "a@b.edu", status: "sent", followupSubject: "Re", followupBody: "Ping", emailConfidence: "found" }),
      which: "followup",
    });
    expect(screen.getByLabelText("Body")).toHaveValue("Ping");
    await fireEvent.click(screen.getByRole("button", { name: "Open in Gmail" }));
    await fireEvent.click(screen.getByRole("button", { name: "Not yet" }));
    expect(screen.queryByText(/Did you send it\?/)).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Open in Gmail" }));
    vi.mocked(applyContactAction).mockResolvedValue(fakeContact({ status: "followed_up" }));
    await fireEvent.click(screen.getByRole("button", { name: "Sent" }));
    expect(vi.mocked(applyContactAction).mock.calls[0][1]).toBe("followed_up");
  });

  it("takes a newer server copy unless the user has unsaved edits", async () => {
    const base = { email: "a@b.edu", status: "sent" as const };
    const { rerender } = render(DraftEditor, { contact: fakeContact(base), which: "followup" });
    expect(screen.getByLabelText("Body")).toHaveValue("");
    await rerender({ contact: fakeContact({ ...base, followupSubject: "Re", followupBody: "From Claude" }), which: "followup" });
    expect(screen.getByLabelText("Body")).toHaveValue("From Claude");
    await fireEvent.input(screen.getByLabelText("Body"), { target: { value: "Mine" } });
    await rerender({ contact: fakeContact({ ...base, followupSubject: "Re", followupBody: "Newer" }), which: "followup" });
    expect(screen.getByLabelText("Body")).toHaveValue("Mine");
  });

  it("does not offer Sent once the draft's action no longer applies", async () => {
    render(DraftEditor, { contact: fakeContact({ ...draft, status: "replied", emailConfidence: "found" }), which: "draft" });
    await fireEvent.click(screen.getByRole("button", { name: "Open in Gmail" }));
    expect(screen.queryByText(/Did you send it\?/)).toBeNull();
  });

  it("replaces Open in Gmail with a Copy note for long drafts", () => {
    render(DraftEditor, { contact: fakeContact({ ...draft, draftBody: "x".repeat(3000) }), which: "draft" });
    expect(screen.queryByRole("button", { name: "Open in Gmail" })).toBeNull();
    expect(screen.getByText(/use Copy/)).toBeInTheDocument();
  });

  it("Save sends the draft fields and Copy writes subject and body", async () => {
    vi.mocked(updateContact).mockResolvedValue(fakeContact({ draftEdited: true }));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(DraftEditor, { contact: fakeContact({ ...draft, id: 2 }), which: "draft" });
    await fireEvent.input(screen.getByLabelText("Body"), { target: { value: "My words" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(updateContact).toHaveBeenCalledWith(2, { draftSubject: "Hello", draftBody: "My words" });
    await fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("Subject: Hello\n\nMy words");
  });
});
