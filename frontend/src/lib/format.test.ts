import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, isoToLocalInput, localInputToIso } from "./format";

describe("format helpers", () => {
  it("localInputToIso converts a datetime-local value to an ISO UTC string", () => {
    const iso = localInputToIso("2026-03-05T14:30");
    expect(iso).toBe(new Date(2026, 2, 5, 14, 30).toISOString());
    expect(iso).toMatch(/Z$/);
  });

  it("localInputToIso returns null for empty or invalid input", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("not a date")).toBeNull();
  });

  it("isoToLocalInput renders an ISO instant in local time for a datetime-local input", () => {
    const iso = new Date(2026, 2, 5, 9, 5).toISOString();
    expect(isoToLocalInput(iso)).toBe("2026-03-05T09:05");
  });

  it("isoToLocalInput round-trips with localInputToIso and handles null/invalid", () => {
    expect(isoToLocalInput(localInputToIso("2026-12-31T23:59")!)).toBe("2026-12-31T23:59");
    expect(isoToLocalInput(null)).toBe("");
    expect(isoToLocalInput("garbage")).toBe("");
  });

  it("formatDateTime uses toLocaleString and falls back to the raw text when unparseable", () => {
    const iso = "2026-03-05T14:30:00Z";
    expect(formatDateTime(iso)).toBe(new Date(iso).toLocaleString());
    expect(formatDateTime("garbage")).toBe("garbage");
  });

  it("formatDate shows a date-only string as that local calendar day (no UTC off-by-one)", () => {
    expect(formatDate("2026-03-05")).toBe(new Date(2026, 2, 5).toLocaleDateString());
    expect(formatDate("garbage")).toBe("garbage");
  });
});
