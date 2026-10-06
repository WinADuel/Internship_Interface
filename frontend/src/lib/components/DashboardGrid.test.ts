import { render } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const destroy = vi.fn();
vi.mock("gridstack", () => ({
  GridStack: { init: vi.fn(() => ({ on: vi.fn(), save: vi.fn(() => []), destroy })) },
}));
vi.mock("gridstack/dist/gridstack.min.css", () => ({}));

import DashboardGrid from "./DashboardGrid.svelte";

const defaultLayout = [
  { id: "a", x: 0, y: 0, w: 4, h: 2, settings: {} },
  { id: "b", x: 4, y: 1, w: 3, h: 5, settings: {} },
];
const widget = createRawSnippet((id: () => string) => ({ render: () => `<span>widget-${id()}</span>` }));

beforeEach(() => localStorage.clear());

describe("DashboardGrid", () => {
  it("renders one item per layout entry with gs attributes", () => {
    const { container, getByText } = render(DashboardGrid, { defaultLayout, widget });
    const items = container.querySelectorAll(".grid-stack-item");
    expect(items).toHaveLength(2);
    expect(items[1].getAttribute("gs-id")).toBe("b");
    expect(items[1].getAttribute("gs-x")).toBe("4");
    expect(items[1].getAttribute("gs-y")).toBe("1");
    expect(items[1].getAttribute("gs-w")).toBe("3");
    expect(items[1].getAttribute("gs-h")).toBe("5");
    getByText("widget-a");
  });

  it("destroys the grid on unmount", () => {
    const { unmount } = render(DashboardGrid, { defaultLayout, widget });
    unmount();
    expect(destroy).toHaveBeenCalledWith(false);
  });
});
