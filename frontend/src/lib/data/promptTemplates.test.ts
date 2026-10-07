import { describe, expect, it } from "vitest";
import { promptTemplates } from "./promptTemplates";

describe("promptTemplates", () => {
  it("includes a draft prompt and a succinct/authentic review prompt", () => {
    const titles = promptTemplates.map((t) => t.title.toLowerCase());
    expect(titles.some((t) => t.includes("draft"))).toBe(true);
    expect(titles.some((t) => t.includes("review"))).toBe(true);
    for (const template of promptTemplates) {
      expect(template.prompt.length).toBeGreaterThan(0);
    }
  });
});
