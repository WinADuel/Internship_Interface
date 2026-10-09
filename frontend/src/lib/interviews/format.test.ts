import { describe, expect, it } from "vitest";
import { countdown, roundName, sortByDate } from "./format";

describe("interview formatting", () => {
  const now = new Date(2026, 9, 9, 10, 0);

  it("counts down by calendar day, and by the hour or minute on the day", () => {
    expect(countdown(new Date(2026, 9, 11, 9, 0).toISOString(), now)).toBe("in 2 days");
    expect(countdown(new Date(2026, 9, 10, 8, 0).toISOString(), now)).toBe("tomorrow");
    expect(countdown(new Date(2026, 9, 9, 13, 0).toISOString(), now)).toBe("in 3 hours");
    expect(countdown(new Date(2026, 9, 9, 10, 30).toISOString(), now)).toBe("in 30 minutes");
    expect(countdown(new Date(2026, 9, 9, 9, 15).toISOString(), now)).toBe("45 minutes ago");
    expect(countdown(new Date(2026, 9, 9, 10, 0).toISOString(), now)).toBe("now");
    expect(countdown(new Date(2026, 9, 8, 23, 0).toISOString(), now)).toBe("yesterday");
    expect(countdown(new Date(2026, 9, 2, 12, 0).toISOString(), now)).toBe("7 days ago");
    expect(countdown("not a date", now)).toBe("");
  });

  it("names a round by its title, else its kind", () => {
    expect(roundName({ title: "Coding round 2", kind: "technical" })).toBe("Coding round 2");
    expect(roundName({ title: "  ", kind: "recruiter_screen" })).toBe("Recruiter screen");
    expect(roundName({ title: null, kind: "other" })).toBe("Interview");
  });

  it("sorts by date with undated rounds last", () => {
    const rows = [
      { id: 1, scheduledAt: null },
      { id: 2, scheduledAt: "2026-10-20T10:00:00Z" },
      { id: 3, scheduledAt: "2026-10-12T10:00:00Z" },
      { id: 4, scheduledAt: null },
    ];
    expect(sortByDate(rows).map((r) => r.id)).toEqual([3, 2, 1, 4]);
    expect(sortByDate(rows, true).map((r) => r.id)).toEqual([2, 3, 1, 4]);
  });
});
