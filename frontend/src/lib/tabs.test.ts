import { describe, expect, it } from "vitest";
import { tabKeyTarget } from "./tabs";

describe("tabKeyTarget", () => {
  it("moves with the arrows, wrapping at both ends", () => {
    expect(tabKeyTarget("ArrowRight", 0, 3)).toBe(1);
    expect(tabKeyTarget("ArrowRight", 2, 3)).toBe(0);
    expect(tabKeyTarget("ArrowLeft", 1, 3)).toBe(0);
    expect(tabKeyTarget("ArrowLeft", 0, 3)).toBe(2);
  });

  it("jumps to the ends with Home and End", () => {
    expect(tabKeyTarget("Home", 2, 3)).toBe(0);
    expect(tabKeyTarget("End", 0, 3)).toBe(2);
  });

  it("ignores other keys", () => {
    expect(tabKeyTarget("Enter", 1, 3)).toBeNull();
    expect(tabKeyTarget("ArrowDown", 1, 3)).toBeNull();
  });
});
