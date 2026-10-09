import { describe, expect, it } from "vitest";
import { splitValidation } from "./validation";

describe("splitValidation", () => {
  const known = new Set(["ranking_role_keywords", "ranking_claude_daily_limit"] as const);

  it("keys known body fields, keeps the first message each, and drops the Value error prefix", () => {
    const { fields, other } = splitValidation(
      [
        { loc: ["body", "ranking_role_keywords"], msg: "Value error, at most 30 items" },
        { loc: ["body", "ranking_role_keywords"], msg: "second" },
        { loc: ["body", "ranking_claude_daily_limit"], msg: "Input should be less than or equal to 150" },
      ],
      known,
    );
    expect(fields).toEqual({
      ranking_role_keywords: "at most 30 items",
      ranking_claude_daily_limit: "Input should be less than or equal to 150",
    });
    expect(other).toEqual([]);
  });

  it("returns anything else as text and skips items without a message", () => {
    const { fields, other } = splitValidation(
      [{ loc: ["body", "discovery_terms"], msg: "bad" }, { loc: ["query", "x"], msg: "odd" }, { loc: ["body"] }, null],
      known,
    );
    expect(fields).toEqual({});
    expect(other).toEqual(["bad", "odd"]);
  });
});
