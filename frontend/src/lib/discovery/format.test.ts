import { describe, expect, it } from "vitest";
import {
  isWebUrl,
  postedAgo,
  postingLabel,
  shortLocations,
  showsSponsorship,
  SOURCE_LABELS,
  sourceLabel,
} from "./format";
import { fakePosting } from "../testing/fixtures";

describe("sourceLabel", () => {
  it("matches the backend labels exactly", () => {
    expect(SOURCE_LABELS).toEqual({
      simplify: "Simplify",
      vanshb03: "vanshb03 list",
      list: "Community list",
      greenhouse: "Greenhouse",
      lever: "Lever",
      ashby: "Ashby",
      workday: "Workday",
      pasted: "Pasted",
    });
    expect(sourceLabel("vanshb03")).toBe("vanshb03 list");
    expect(sourceLabel("pasted")).toBe("Pasted");
  });
});

describe("postedAgo", () => {
  const now = new Date(2026, 9, 8, 9, 30); // 8 Oct 2026, 09:30 local

  it("returns an empty string for no date or an unparseable one", () => {
    expect(postedAgo(null, now)).toBe("");
    expect(postedAgo("garbage", now)).toBe("");
  });

  it("says today for the same local calendar day, early or late", () => {
    expect(postedAgo(new Date(2026, 9, 8, 0, 1).toISOString(), now)).toBe("today");
    expect(postedAgo(new Date(2026, 9, 8, 23, 59).toISOString(), now)).toBe("today");
  });

  it("counts calendar days, not 24-hour periods", () => {
    expect(postedAgo(new Date(2026, 9, 7, 23, 59).toISOString(), now)).toBe("1 day ago");
    expect(postedAgo(new Date(2026, 9, 7, 0, 0).toISOString(), now)).toBe("1 day ago");
    expect(postedAgo(new Date(2026, 9, 6, 12, 0).toISOString(), now)).toBe("2 days ago");
  });

  it("uses days below two weeks and whole weeks from 14 days", () => {
    expect(postedAgo(new Date(2026, 8, 25, 12, 0).toISOString(), now)).toBe("13 days ago");
    expect(postedAgo(new Date(2026, 8, 24, 12, 0).toISOString(), now)).toBe("2 weeks ago");
    expect(postedAgo(new Date(2026, 8, 18, 12, 0).toISOString(), now)).toBe("2 weeks ago"); // 20 days
    expect(postedAgo(new Date(2026, 8, 17, 12, 0).toISOString(), now)).toBe("3 weeks ago"); // 21 days
    expect(postedAgo(new Date(2025, 9, 8, 12, 0).toISOString(), now)).toBe("52 weeks ago");
  });

  it("reads a date-only value as that local day", () => {
    expect(postedAgo("2026-10-08", now)).toBe("today");
    expect(postedAgo("2026-10-07", now)).toBe("1 day ago");
  });

  it("treats a future date as today", () => {
    expect(postedAgo(new Date(2026, 9, 10, 12, 0).toISOString(), now)).toBe("today");
  });

  it("counts across a daylight-saving change by calendar day", () => {
    // Spans the US/EU autumn clock change; still 7 calendar days wherever the test runs.
    const later = new Date(2026, 10, 3, 9, 0);
    expect(postedAgo(new Date(2026, 9, 27, 9, 0).toISOString(), later)).toBe("7 days ago");
  });
});

describe("postingLabel", () => {
  it("joins company and title with an en dash", () => {
    expect(postingLabel(fakePosting({ company: "Stripe", title: "SWE Intern" }))).toBe("Stripe – SWE Intern");
  });
});

describe("shortLocations", () => {
  it("shows up to two locations and counts the rest", () => {
    expect(shortLocations([])).toBe("");
    expect(shortLocations(["NYC"])).toBe("NYC");
    expect(shortLocations(["NYC", "Remote"])).toBe("NYC, Remote");
    expect(shortLocations(["NYC", "Remote", "SF", "LA"])).toBe("NYC, Remote +2 more");
  });
});

describe("isWebUrl", () => {
  it("accepts only http and https URLs", () => {
    expect(isWebUrl("https://stripe.com/jobs/1")).toBe(true);
    expect(isWebUrl("HTTP://stripe.com")).toBe(true);
    expect(isWebUrl("javascript:alert(1)")).toBe(false);
    expect(isWebUrl(" https://x.com")).toBe(false);
    expect(isWebUrl("data:text/html,hi")).toBe(false);
    expect(isWebUrl("//evil.com")).toBe(false);
    expect(isWebUrl("")).toBe(false);
  });
});

describe("showsSponsorship", () => {
  it("shows a note only when there is one and it is not Other", () => {
    expect(showsSponsorship(null)).toBe(false);
    expect(showsSponsorship("")).toBe(false);
    expect(showsSponsorship("Other")).toBe(false);
    expect(showsSponsorship(" other ")).toBe(false);
    expect(showsSponsorship("Does Not Offer Sponsorship")).toBe(true);
  });
});
