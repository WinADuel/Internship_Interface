import { render } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const destroy = vi.fn();
const on = vi.fn();
const save = vi.fn(() => [] as unknown[]);
const getColumn = vi.fn(() => 12);
vi.mock("gridstack", () => ({
  GridStack: { init: vi.fn(() => ({ on, save, getColumn, destroy })) },
}));
vi.mock("gridstack/dist/gridstack.min.css", () => ({}));

import { GridStack } from "gridstack";
import DashboardGrid from "./DashboardGrid.svelte";

const defaultLayout = [
  { id: "a", x: 0, y: 0, w: 4, h: 2, settings: {} },
  { id: "b", x: 4, y: 1, w: 3, h: 5, settings: {} },
];
const widget = createRawSnippet((id: () => string) => ({ render: () => `<span>widget-${id()}</span>` }));

beforeEach(() => {
  localStorage.clear();
  on.mockClear();
  save.mockReset().mockReturnValue([]);
  getColumn.mockReset().mockReturnValue(12);
});

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

  it("collapses to a single column on narrow screens", () => {
    render(DashboardGrid, { defaultLayout, widget });
    const options = vi.mocked(GridStack.init).mock.calls.at(-1)![0] as any;
    expect(options.columnOpts).toEqual({ breakpointForWindow: true, breakpoints: [{ w: 700, c: 1 }] });
  });

  it("does not persist the stacked single-column geometry over the saved desktop layout", async () => {
    const { LAYOUT_STORAGE_KEY } = await import("../dashboard/layout");
    render(DashboardGrid, { defaultLayout, widget });
    const onChange = on.mock.calls.find((c) => c[0] === "change")![1] as () => void;
    localStorage.removeItem(LAYOUT_STORAGE_KEY);

    getColumn.mockReturnValue(1);
    save.mockReturnValue([{ id: "a", x: 0, y: 0, w: 1, h: 2 }, { id: "b", x: 0, y: 2, w: 1, h: 5 }]);
    onChange();
    expect(localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();

    getColumn.mockReturnValue(12);
    save.mockReturnValue([{ id: "a", x: 0, y: 0, w: 5, h: 2 }, { id: "b", x: 5, y: 0, w: 3, h: 5 }]);
    onChange();
    const saved = JSON.parse(localStorage.getItem(LAYOUT_STORAGE_KEY)!);
    expect(saved.find((e: any) => e.id === "b")).toMatchObject({ x: 5, w: 3, h: 5 });
  });

  it("destroys the grid on unmount", () => {
    const { unmount } = render(DashboardGrid, { defaultLayout, widget });
    unmount();
    expect(destroy).toHaveBeenCalledWith(false);
  });
});

describe("DashboardGrid updateSettings", () => {
  it("merges settings into the entry and persists them", async () => {
    const { LAYOUT_STORAGE_KEY } = await import("../dashboard/layout");
    const { component } = render(DashboardGrid, { defaultLayout, widget });
    (component as any).updateSettings("b", { limit: 7 });
    (component as any).updateSettings("b", { extra: 1 });
    const saved = JSON.parse(localStorage.getItem(LAYOUT_STORAGE_KEY)!);
    expect(saved.find((e: any) => e.id === "b").settings).toEqual({ limit: 7, extra: 1 });
    expect(saved.find((e: any) => e.id === "a").settings).toEqual({});
  });
});
