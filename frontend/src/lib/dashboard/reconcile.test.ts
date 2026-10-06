import { beforeEach, describe, expect, it } from "vitest";
import { loadLayout, reconcileLayout, saveLayout } from "./layout";

const e = (id: string, x = 0) => ({ id, x, y: 0, w: 2, h: 2, settings: {} });

beforeEach(() => localStorage.clear());

describe("reconcileLayout", () => {
  it("appends default entries missing from the saved layout", () => {
    expect(reconcileLayout([e("a", 5)], [e("a"), e("b")])).toEqual([e("a", 5), e("b")]);
  });
  it("drops saved entries whose id is not in the defaults", () => {
    expect(reconcileLayout([e("a"), e("gone")], [e("a")])).toEqual([e("a")]);
  });
  it("dedupes ids keeping the first occurrence", () => {
    expect(reconcileLayout([e("a", 1), e("a", 9)], [e("a")])).toEqual([e("a", 1)]);
  });
  it("is applied by loadLayout", () => {
    saveLayout([e("old"), e("a", 3)]);
    expect(loadLayout([e("a"), e("b")])).toEqual([e("a", 3), e("b")]);
  });
});
