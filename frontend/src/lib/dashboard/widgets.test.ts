import { describe, expect, it } from "vitest";
import { fakeApplication } from "../testing/fixtures";
import { bucketApplications, countByStatus, overdueFollowUps, upcomingReminders } from "./widgets";

describe("widgets", () => {
  it("upcomingReminders includes only dates within the window and excludes archived", () => {
    const now = new Date("2026-10-05T00:00:00Z");
    const apps = [
      fakeApplication({ id: 1, followUpDate: "2026-10-10", archived: false }),
      fakeApplication({ id: 2, followUpDate: "2026-11-10", archived: false }),
      fakeApplication({ id: 3, followUpDate: "2026-10-06", archived: true }),
    ];
    expect(upcomingReminders(apps, 14, now).map((a) => a.id)).toEqual([1]);
  });

  it("includes a follow-up due today when now is mid-afternoon", () => {
    const now = new Date(2026, 9, 5, 15, 30);
    const apps = [fakeApplication({ id: 1, followUpDate: "2026-10-05" })];
    expect(upcomingReminders(apps, 7, now).map((a) => a.id)).toEqual([1]);
  });

  it("excludes a follow-up from yesterday", () => {
    const now = new Date(2026, 9, 5, 15, 30);
    const apps = [fakeApplication({ id: 1, followUpDate: "2026-10-04" })];
    expect(upcomingReminders(apps, 7, now)).toEqual([]);
  });

  it("excludes an interview earlier today that is already past", () => {
    const now = new Date(2026, 9, 5, 15, 30);
    const apps = [fakeApplication({ id: 1, interviewDatetime: new Date(2026, 9, 5, 9, 0).toISOString() })];
    expect(upcomingReminders(apps, 7, now)).toEqual([]);
  });

  it("sorts an app with both fields qualifying by the earlier one", () => {
    const now = new Date(2026, 9, 5, 15, 30);
    const apps = [
      fakeApplication({ id: 1, followUpDate: "2026-10-12", interviewDatetime: new Date(2026, 9, 7, 10, 0).toISOString() }),
      fakeApplication({ id: 2, followUpDate: "2026-10-09" }),
      fakeApplication({ id: 3, followUpDate: "2026-10-08", interviewDatetime: new Date(2026, 9, 11, 10, 0).toISOString() }),
    ];
    expect(upcomingReminders(apps, 14, now).map((a) => a.id)).toEqual([1, 3, 2]);
  });

  it("bucketApplications maps statuses to the three buckets and excludes archived", () => {
    const apps = [
      fakeApplication({ id: 1, status: "wishlist", archived: false }),
      fakeApplication({ id: 2, status: "interview", archived: false }),
      fakeApplication({ id: 3, status: "offer", archived: false }),
      fakeApplication({ id: 4, status: "offer", archived: true }),
    ];
    const buckets = bucketApplications(apps);
    expect(buckets.undone.map((a) => a.id)).toEqual([1]);
    expect(buckets.workingOn.map((a) => a.id)).toEqual([2]);
    expect(buckets.completed.map((a) => a.id)).toEqual([3]);
  });

  it("countByStatus tallies non-archived applications per status", () => {
    const apps = [
      fakeApplication({ id: 1, status: "applied", archived: false }),
      fakeApplication({ id: 2, status: "applied", archived: false }),
      fakeApplication({ id: 3, status: "applied", archived: true }),
    ];
    const counts = countByStatus(apps);
    expect(counts.applied).toBe(2);
    expect(counts.wishlist).toBe(0);
  });

  describe("overdueFollowUps", () => {
    const now = new Date(2026, 9, 5, 15, 30);

    it("returns follow-ups before today's local day, oldest first", () => {
      const apps = [
        fakeApplication({ id: 1, followUpDate: "2026-10-04" }),
        fakeApplication({ id: 2, followUpDate: "2026-09-01" }),
        fakeApplication({ id: 3, followUpDate: "2026-10-02" }),
      ];
      expect(overdueFollowUps(apps, now).map((a) => a.id)).toEqual([2, 3, 1]);
    });

    it("excludes today, the future, and applications without a follow-up date", () => {
      const apps = [
        fakeApplication({ id: 1, followUpDate: "2026-10-05" }),
        fakeApplication({ id: 2, followUpDate: "2026-10-06" }),
        fakeApplication({ id: 3, followUpDate: null }),
      ];
      expect(overdueFollowUps(apps, now)).toEqual([]);
    });

    it("excludes today even just after local midnight", () => {
      const justAfterMidnight = new Date(2026, 9, 5, 0, 0, 1);
      const apps = [fakeApplication({ id: 1, followUpDate: "2026-10-05" })];
      expect(overdueFollowUps(apps, justAfterMidnight)).toEqual([]);
    });

    it("excludes archived applications and those already at offer or rejected", () => {
      const apps = [
        fakeApplication({ id: 1, followUpDate: "2026-10-01", archived: true }),
        fakeApplication({ id: 2, followUpDate: "2026-10-01", status: "offer" }),
        fakeApplication({ id: 3, followUpDate: "2026-10-01", status: "rejected" }),
        fakeApplication({ id: 4, followUpDate: "2026-10-01", status: "applied" }),
        fakeApplication({ id: 5, followUpDate: "2026-10-01", status: "wishlist" }),
      ];
      expect(overdueFollowUps(apps, now).map((a) => a.id)).toEqual([4, 5]);
    });

    it("does not change what upcomingReminders returns (yesterday still excluded there)", () => {
      const apps = [fakeApplication({ id: 1, followUpDate: "2026-10-04" })];
      expect(upcomingReminders(apps, 7, now)).toEqual([]);
      expect(overdueFollowUps(apps, now).map((a) => a.id)).toEqual([1]);
    });
  });
});
