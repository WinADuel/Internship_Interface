import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";

vi.mock("../../api/contacts", () => ({ applyContactAction: vi.fn(), undoContactAction: vi.fn() }));

import ContactCard from "./ContactCard.svelte";

describe("ContactCard", () => {
  it("shows Draft ready only for to_contact with a draft", () => {
    const { unmount } = render(ContactCard, { contact: fakeContact({ draftBody: "Hi" }) });
    expect(screen.getByText("Draft ready")).toBeInTheDocument();
    unmount();
    render(ContactCard, { contact: fakeContact({ draftBody: "Hi", status: "sent" }) });
    expect(screen.queryByText("Draft ready")).toBeNull();
  });

  it("shows the email-confidence and nudge badges", () => {
    render(ContactCard, { contact: fakeContact({ emailConfidence: "pattern_guess", nudge: "followup_due", status: "sent" }) });
    expect(screen.getByText("Email guessed")).toBeInTheDocument();
    expect(screen.getByText("Follow-up due")).toBeInTheDocument();
  });

  it("renders hostile markup as literal text", () => {
    const { container } = render(ContactCard, { contact: fakeContact({ name: "<b>x</b>", title: "<img src=x>" }) });
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("is draggable with its id and opens on click", async () => {
    const onopen = vi.fn();
    const contact = fakeContact({ id: 9 });
    const { container } = render(ContactCard, { contact, onopen });
    const card = container.querySelector("article")!;
    expect(card.getAttribute("draggable")).toBe("true");
    const setData = vi.fn();
    await fireEvent.dragStart(card, { dataTransfer: { setData } });
    expect(setData).toHaveBeenCalledWith("text/plain", "9");
    await fireEvent.click(screen.getByRole("button", { name: "Jane Lee" }));
    expect(onopen).toHaveBeenCalledWith(contact);
  });

  it("compact mode hides the status buttons", () => {
    render(ContactCard, { contact: fakeContact(), compact: true });
    expect(screen.queryByRole("button", { name: "Sent" })).toBeNull();
  });
});
