import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api/researchQueue", () => ({ listQueue: vi.fn(), addQueueItem: vi.fn() }));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import { addQueueItem, listQueue } from "../lib/api/researchQueue";
import type { QueueItem } from "../lib/types/contact";
import ResearchQueue from "./ResearchQueue.svelte";

function item(overrides: Partial<QueueItem>): QueueItem {
  return {
    id: 1, kind: "professor_person", requestText: "Jane Lee, Stanford", applicationId: null, targetCount: 1,
    state: "pending", resultNote: null, createdAt: "2026-10-01T09:00:00Z", completedAt: null, ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(listQueue).mockReset().mockResolvedValue([
    item({ id: 1 }),
    item({ id: 2, state: "failed", requestText: "Prof X", resultNote: "<b>could not identify</b>" }),
  ]);
  vi.mocked(addQueueItem).mockReset();
});

describe("ResearchQueue page", () => {
  it("adds a search brief with its target count", async () => {
    vi.mocked(addQueueItem).mockResolvedValue(
      item({ id: 3, kind: "professor_search", requestText: "5 ML-for-robotics profs at UIUC", targetCount: 5 }),
    );
    render(ResearchQueue);
    await fireEvent.click(screen.getByRole("button", { name: "Search brief" }));
    await fireEvent.input(screen.getByLabelText("What to look for"), {
      target: { value: "5 ML-for-robotics profs at UIUC" },
    });
    await fireEvent.input(screen.getByLabelText("How many"), { target: { value: "5" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add to queue" }));
    expect(addQueueItem).toHaveBeenCalledWith({
      kind: "professor_search",
      requestText: "5 ML-for-robotics profs at UIUC",
      targetCount: 5,
    });
    expect(await screen.findByText("5 ML-for-robotics profs at UIUC")).toBeInTheDocument();
  });

  it("groups items and shows a failed item's note as plain text", async () => {
    const { container } = render(ResearchQueue);
    expect(await screen.findByText("<b>could not identify</b>")).toBeInTheDocument();
    expect(container.querySelector("li b")).toBeNull();
    expect(screen.getByRole("heading", { name: "Pending (1)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Failed (1)" })).toBeInTheDocument();
  });

  it("explains that the daily Claude job processes requests", () => {
    render(ResearchQueue);
    expect(screen.getByText(/daily Claude job/)).toBeInTheDocument();
  });
});
