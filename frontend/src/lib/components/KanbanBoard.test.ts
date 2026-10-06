import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { applications } from "../stores/applications";
import { fakeApplication } from "../testing/fixtures";

vi.mock("../stores/applications", async (orig) => {
  const actual = await orig<typeof import("../stores/applications")>();
  return { ...actual, moveApplicationStatus: vi.fn() };
});
vi.mock("../stores/toast", () => ({ showToast: vi.fn() }));

import { moveApplicationStatus } from "../stores/applications";
import { showToast } from "../stores/toast";
import KanbanBoard from "./KanbanBoard.svelte";

function dropOn(column: HTMLElement, data: string) {
  return fireEvent.drop(column, { dataTransfer: { getData: () => data } });
}

describe("KanbanBoard", () => {
  beforeEach(() => {
    vi.mocked(moveApplicationStatus).mockReset();
    vi.mocked(showToast).mockReset();
    applications.set([fakeApplication({ id: 7, company: "Globex", status: "wishlist" })]);
  });

  it("renders a column per status with cards", () => {
    render(KanbanBoard);
    expect(screen.getAllByRole("region")).toHaveLength(6);
    expect(screen.getByText("Globex")).toBeTruthy();
  });

  it("moves the dropped application", async () => {
    vi.mocked(moveApplicationStatus).mockResolvedValue();
    render(KanbanBoard);
    await dropOn(screen.getByRole("region", { name: "Applied" }), "7");
    expect(moveApplicationStatus).toHaveBeenCalledWith(7, "applied");
  });

  it("ignores garbage drag data", async () => {
    render(KanbanBoard);
    await dropOn(screen.getByRole("region", { name: "Applied" }), "abc");
    await dropOn(screen.getByRole("region", { name: "Applied" }), "");
    expect(moveApplicationStatus).not.toHaveBeenCalled();
  });

  it("shows a toast when a move fails", async () => {
    vi.mocked(moveApplicationStatus).mockRejectedValue(new Error("boom"));
    render(KanbanBoard);
    await dropOn(screen.getByRole("region", { name: "Applied" }), "7");
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Couldn't move application — try again."),
    );
  });
});
