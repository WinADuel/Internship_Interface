import { beforeEach, describe, expect, it, vi } from "vitest";
import { LAYOUT_STORAGE_KEY, loadLayout, reconcileLayout, saveLayout } from "./layout";

const defaults = [{ id: "activity", x: 0, y: 0, w: 4, h: 2, settings: {} }];

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("layout persistence", () => {
  it("returns defaults when nothing is stored", () => {
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("returns the stored layout when present", () => {
    const stored = [{ id: "activity", x: 1, y: 1, w: 6, h: 3, settings: { limit: 5 } }];
    saveLayout(stored);
    expect(loadLayout(defaults)).toEqual(stored);
  });

  it("falls back to defaults on corrupted storage", () => {
    localStorage.setItem(LAYOUT_STORAGE_KEY, "not-json");
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("falls back to defaults when stored value is not an array", () => {
    localStorage.setItem(LAYOUT_STORAGE_KEY, '{"id":"a"}');
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("falls back to defaults when getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("does not throw when setItem throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveLayout(defaults)).not.toThrow();
  });

  it("falls back to defaults when an entry is missing w", () => {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify([{ id: "a", x: 0, y: 0, h: 2, settings: {} }]));
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("falls back to defaults when x is a string", () => {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify([{ id: "a", x: "1", y: 0, w: 2, h: 2, settings: {} }]));
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("falls back to defaults when settings is not a plain object, or id not a string", () => {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify([{ id: "a", x: 0, y: 0, w: 2, h: 2, settings: [] }]));
    expect(loadLayout(defaults)).toEqual(defaults);
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify([{ id: 5, x: 0, y: 0, w: 2, h: 2, settings: {} }]));
    expect(loadLayout(defaults)).toEqual(defaults);
  });

  it("falls back to defaults if any one entry is malformed", () => {
    const good = { id: "a", x: 0, y: 0, w: 2, h: 2, settings: {} };
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify([good, { ...good, id: "b", h: null }]));
    expect(loadLayout(defaults)).toEqual(defaults);
  });
});
