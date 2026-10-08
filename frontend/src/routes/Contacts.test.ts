import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../lib/testing/fixtures";

vi.mock("../lib/api/contacts", () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  getContactHistory: vi.fn().mockResolvedValue([]),
  moveContactStatus: vi.fn(),
  applyContactAction: vi.fn(),
  undoContactAction: vi.fn(),
  updateContact: vi.fn(),
  archiveContact: vi.fn(),
}));

import { createContact, listContacts } from "../lib/api/contacts";
import Contacts from "./Contacts.svelte";

beforeEach(() => {
  vi.mocked(listContacts).mockReset().mockResolvedValue([fakeContact({ id: 1, name: "Jane Lee" })]);
  vi.mocked(createContact).mockReset();
});

describe("Contacts page", () => {
  it("opens the detail panel and closes it on Escape", async () => {
    render(Contacts);
    await fireEvent.click(await screen.findByRole("button", { name: "Jane Lee" }));
    expect(screen.getByLabelText("Contact details")).toBeInTheDocument();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByLabelText("Contact details")).toBeNull();
  });

  it("adds a contact and opens it", async () => {
    vi.mocked(createContact).mockResolvedValue(fakeContact({ id: 2, name: "Sam", kind: "company", organization: "Stripe" }));
    render(Contacts);
    await fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
    await fireEvent.change(screen.getByLabelText("Type"), { target: { value: "company" } });
    await fireEvent.input(screen.getByLabelText("Name"), { target: { value: " Sam " } });
    await fireEvent.input(screen.getByLabelText("Organization"), { target: { value: "Stripe" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(createContact).toHaveBeenCalledWith({ kind: "company", name: "Sam", organization: "Stripe", email: null, title: null });
    expect(await screen.findByLabelText("Contact details")).toBeInTheDocument();
  });
});
