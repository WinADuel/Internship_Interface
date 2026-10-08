import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeContact } from "../../testing/fixtures";
import { ApiError } from "../../api/client";

vi.mock("../../api/contacts", () => ({
  listContacts: vi.fn(),
  moveContactStatus: vi.fn(),
  applyContactAction: vi.fn(),
  undoContactAction: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { listContacts, moveContactStatus } from "../../api/contacts";
import { showToast } from "../../stores/toast";
import ContactBoard from "./ContactBoard.svelte";

const prof = fakeContact({ id: 1, name: "Prof", kind: "professor" });
const comp = fakeContact({ id: 2, name: "Recruiter", kind: "company", organization: "Stripe" });
const gone = fakeContact({ id: 3, name: "Gone", archived: true });

beforeEach(() => {
  vi.mocked(listContacts).mockReset().mockImplementation(async (opts = {}) =>
    [prof, comp, gone].filter((c) => !opts.kind || c.kind === opts.kind),
  );
  vi.mocked(moveContactStatus).mockReset();
  vi.mocked(showToast).mockReset();
});

function dropOn(column: HTMLElement, data: string) {
  return fireEvent.drop(column, { dataTransfer: { getData: () => data } });
}

describe("ContactBoard", () => {
  it("renders a column per status and hides archived contacts", async () => {
    render(ContactBoard);
    expect(await screen.findByText("Prof")).toBeInTheDocument();
    expect(screen.getAllByRole("region")).toHaveLength(7);
    expect(screen.queryByText("Gone")).toBeNull();
  });

  it("filters by kind and relabels accepted for company", async () => {
    render(ContactBoard);
    await screen.findByText("Prof");
    await fireEvent.click(screen.getByRole("button", { name: "Company" }));
    expect(listContacts).toHaveBeenLastCalledWith({ kind: "company" });
    expect(await screen.findByRole("region", { name: "Positive (referral/interview)" })).toBeInTheDocument();
    expect(screen.queryByText("Prof")).toBeNull();
  });

  it("drop moves the contact; an invalid move shows the backend detail", async () => {
    render(ContactBoard);
    await screen.findByText("Prof");
    vi.mocked(moveContactStatus).mockResolvedValue({ ...prof, status: "sent" });
    await dropOn(screen.getByRole("region", { name: "Sent" }), "1");
    expect(moveContactStatus).toHaveBeenCalledWith(1, "sent");
    vi.mocked(moveContactStatus).mockRejectedValue(new ApiError(422, "cannot move a contact from 'sent' to 'meeting'"));
    await dropOn(screen.getByRole("region", { name: "Meeting" }), "1");
    expect(showToast).toHaveBeenCalledWith("cannot move a contact from 'sent' to 'meeting'");
  });

  it("ignores garbage drag data", async () => {
    render(ContactBoard);
    await screen.findByText("Prof");
    await dropOn(screen.getByRole("region", { name: "Sent" }), "abc");
    expect(moveContactStatus).not.toHaveBeenCalled();
  });
});
