import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";
import { ApiError } from "../../api/client";

vi.mock("../../api/contacts", () => ({ listContacts: vi.fn() }));
vi.mock("../../api/researchQueue", () => ({ findContacts: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { listContacts } from "../../api/contacts";
import { findContacts } from "../../api/researchQueue";
import { showToast } from "../../stores/toast";
import ApplicationContacts from "./ApplicationContacts.svelte";

beforeEach(() => {
  vi.mocked(listContacts).mockReset().mockResolvedValue([]);
  vi.mocked(findContacts).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("ApplicationContacts", () => {
  it("lists the application's company contacts", async () => {
    vi.mocked(listContacts).mockResolvedValue([fakeContact({ kind: "company", name: "Sam", draftBody: "Hi" })]);
    render(ApplicationContacts, { applicationId: 5 });
    expect(await screen.findByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("Draft ready")).toBeInTheDocument();
    expect(listContacts).toHaveBeenCalledWith({ kind: "company", applicationId: 5 });
  });

  it("shows the empty state", async () => {
    render(ApplicationContacts, { applicationId: 5 });
    expect(await screen.findByText("No contacts yet — they'll appear after the daily Claude run.")).toBeInTheDocument();
  });

  it("Find contacts queues once and explains a 409", async () => {
    vi.mocked(findContacts).mockRejectedValue(new ApiError(409, "already queued"));
    render(ApplicationContacts, { applicationId: 5 });
    await fireEvent.click(screen.getByRole("button", { name: "Find contacts" }));
    expect(findContacts).toHaveBeenCalledWith(5);
    expect(showToast).toHaveBeenCalledWith("Contacts already queued for this application.");
  });
});
